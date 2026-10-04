import pandas as pd
import pytest

from src.cleaning import clean_orders, steps_to_frame

BASE_MAP = {
    "customer_id": "cust",
    "order_date": "date",
    "order_value": "amount",
    "order_status": "status",
}


def hand_frame():
    """16 rows built so each rule removes a known number of rows."""
    rows = [
        # cust, date, amount, status
        ("a@x.com", "2025-01-05", "$10.00", "paid"),            # keep
        ("A@X.com", "2025-02-05", "20", "Completed"),           # keep, same customer as above
        ("b", "not a date", "15", "paid"),                      # rule 1
        ("b", "", "15", "paid"),                                # rule 1
        ("c", "2025-01-10", "abc", "paid"),                     # rule 2
        ("c", "2025-01-11", "", "paid"),                        # rule 2
        ("d", "2025-01-12", "30", "Refunded"),                  # rule 3
        ("d", "2025-01-13", "30", "voided"),                    # rule 3
        ("e", "2025-01-14", "30", "partially refunded"),        # keep
        ("f", "2025-01-15", "-5", "paid"),                      # rule 4
        ("g", "2025-01-16", "0", "paid"),                       # rule 5
        ("h", "2025-01-17", "0.00", "paid"),                    # rule 5
        ("", "2025-01-18", "12", "paid"),                       # rule 6
        ("Guest", "2025-01-19", "12", "paid"),                  # rule 6
        ("i", "2025-01-20", "40", "paid"),                      # keep
        ("i", "2025-01-20", "40", "paid"),                      # keep, exact duplicate
    ]
    return pd.DataFrame(rows, columns=["cust", "date", "amount", "status"])


def removed(result):
    return {s.number: s.rows_removed for s in result.steps}


def test_every_rule_count_matches_the_hand_count():
    r = clean_orders(hand_frame(), BASE_MAP)
    assert removed(r) == {1: 2, 2: 2, 3: 2, 4: 1, 5: 2, 6: 2, 7: 0, 8: 0}
    assert len(r.steps) == 8
    assert len(r.frame) == 5
    assert list(r.frame.columns) == ["customer_id", "order_date", "order_value"]


def test_stats_match_the_hand_count():
    s = clean_orders(hand_frame(), BASE_MAP).stats
    assert s["rows_in"] == 16
    assert s["orders"] == 5
    assert s["customers"] == 3
    assert s["total_revenue"] == pytest.approx(140.0)
    assert s["repeat_customer_share"] == pytest.approx(2 / 3)
    assert s["first_date"] == pd.Timestamp("2025-01-05")
    assert s["last_date"] == pd.Timestamp("2025-02-05")


def test_emails_are_lowercased_and_merge_into_one_customer():
    frame = clean_orders(hand_frame(), BASE_MAP).frame
    assert (frame["customer_id"] == "a@x.com").sum() == 2


def test_partial_refund_is_kept():
    frame = clean_orders(hand_frame(), BASE_MAP).frame
    assert "e" in set(frame["customer_id"])


def test_exact_duplicates_without_order_id_are_kept_and_warned():
    r = clean_orders(hand_frame(), BASE_MAP)
    assert (r.frame["customer_id"] == "i").sum() == 2
    assert any("exactly repeat another row" in w for w in r.warnings)


def test_quality_warnings_fire_on_the_small_sample():
    text = " ".join(clean_orders(hand_frame(), BASE_MAP).warnings)
    assert "fewer than 200" in text
    assert "fewer than 50" in text
    assert "span 31 days" in text
    assert "dropped 69%" in text
    assert "No customer ordered more than once" not in text


def test_no_repeat_customers_warning():
    df = pd.DataFrame({"cust": ["a", "b", "c"], "date": ["2025-01-01"] * 3, "amount": ["5"] * 3})
    r = clean_orders(df, {k: v for k, v in BASE_MAP.items() if k != "order_status"})
    assert any("No customer ordered more than once" in w for w in r.warnings)
    assert r.stats["repeat_customer_share"] == 0.0


def order_id_frame():
    rows = [
        ("o1", "a", "2025-01-01", "10"),
        ("o1", "a", "2025-01-01", "5"),
        ("o2", "b", "2025-01-02", "7"),
        ("o2", "b", "2025-01-02", "7"),
        ("", "c", "2025-01-03", "9"),
        ("", "c", "2025-01-03", "9"),
        ("o3", "d", "2025-01-04", "20"),
        ("o3", "d", "2025-01-04", "0"),   # zero line is removed by rule 5 before combining
    ]
    return pd.DataFrame(rows, columns=["oid", "cust", "date", "amount"])


ID_MAP = {"customer_id": "cust", "order_date": "date", "order_value": "amount", "order_id": "oid"}


def test_line_items_are_summed():
    r = clean_orders(order_id_frame(), ID_MAP, line_item_mode="sum")
    assert removed(r)[5] == 1
    assert removed(r)[7] == 2  # 7 rows reach rule 7, 5 orders come out
    assert len(r.frame) == 5
    by_id = r.frame.set_index("order_id")["order_value"]
    assert by_id["o1"] == 15 and by_id["o2"] == 14 and by_id["o3"] == 20
    assert r.stats["total_revenue"] == pytest.approx(15 + 14 + 20 + 9 + 9)


def test_line_items_take_first_value():
    r = clean_orders(order_id_frame(), ID_MAP, line_item_mode="first")
    by_id = r.frame.set_index("order_id")["order_value"]
    assert by_id["o1"] == 10 and by_id["o2"] == 7
    assert r.stats["total_revenue"] == pytest.approx(10 + 7 + 20 + 9 + 9)


def test_blank_order_ids_stay_separate_and_duplicates_are_flagged():
    r = clean_orders(order_id_frame(), ID_MAP)
    assert (r.frame["order_id"] == "").sum() == 2
    assert any(w.startswith("1 row exactly repeat") for w in r.warnings)
    assert r.steps[7].why.startswith("1 row ")


def test_quantity_times_unit_price_with_invoice_lines():
    rows = [
        ("inv1", "c1", "2025-01-01", "2", "3.50"),   # 7.00
        ("inv1", "c1", "2025-01-01", "1", "4.00"),   # 4.00, same invoice, total 11.00
        ("inv2", "c2", "2025-01-02", "x", "2.00"),   # rule 2, unreadable quantity
        ("inv3", "c3", "2025-01-03", "0", "2.00"),   # rule 5, value 0
        ("inv4", "c4", "2025-01-04", "3", "1.00"),   # 3.00
    ]
    df = pd.DataFrame(rows, columns=["inv", "cust", "date", "qty", "price"])
    m = {"customer_id": "cust", "order_date": "date", "order_value": "price",
         "order_id": "inv", "quantity": "qty"}
    r = clean_orders(df, m, multiply_quantity=True)
    assert removed(r)[2] == 1 and removed(r)[5] == 1 and removed(r)[7] == 1
    assert r.stats["orders"] == 2
    assert r.stats["total_revenue"] == pytest.approx(14.0)


def test_ambiguous_numeric_dates_assume_month_first_and_warn():
    df = pd.DataFrame({"cust": ["a", "b"], "date": ["03/04/2025", "05/06/2025"], "amount": ["5", "6"]})
    m = {"customer_id": "cust", "order_date": "date", "order_value": "amount"}
    r = clean_orders(df, m)
    assert r.frame["order_date"].iloc[0] == pd.Timestamp("2025-03-04")
    assert any("Month first was assumed" in w for w in r.warnings)
    flipped = clean_orders(df, m, dayfirst=True)
    assert flipped.frame["order_date"].iloc[0] == pd.Timestamp("2025-04-03")
    assert not any("Month first was assumed" in w for w in flipped.warnings)


def test_day_first_is_detected_when_a_day_exceeds_12():
    df = pd.DataFrame({"cust": ["a", "b"], "date": ["25/03/2025", "01/02/2025"], "amount": ["5", "6"]})
    r = clean_orders(df, {"customer_id": "cust", "order_date": "date", "order_value": "amount"})
    assert r.stats["dayfirst_used"] is True
    assert r.frame["order_date"].min() == pd.Timestamp("2025-02-01")
    assert not any("Month first was assumed" in w for w in r.warnings)


def test_everything_removed_gives_a_warning_not_a_crash():
    df = pd.DataFrame({"cust": ["a"], "date": ["bad"], "amount": ["5"]})
    r = clean_orders(df, {"customer_id": "cust", "order_date": "date", "order_value": "amount"})
    assert len(r.frame) == 0
    assert r.stats["orders"] == 0 and r.stats["first_date"] is None
    assert r.warnings == ["No orders are left after cleaning. Check the column matches and the date format."]


@pytest.mark.parametrize(
    "mapping, kwargs, message",
    [
        ({"customer_id": "cust", "order_date": "date"}, {}, "order_value"),
        (BASE_MAP, {"line_item_mode": "max"}, "sum"),
        (BASE_MAP, {"multiply_quantity": True}, "quantity"),
        ({**BASE_MAP, "order_value": "missing"}, {}, "missing"),
    ],
)
def test_bad_inputs_raise_plain_errors(mapping, kwargs, message):
    with pytest.raises(ValueError, match=message):
        clean_orders(hand_frame(), mapping, **kwargs)


def test_empty_file_raises():
    with pytest.raises(ValueError, match="no rows"):
        clean_orders(hand_frame().iloc[0:0], BASE_MAP)


def test_steps_table_has_one_line_per_rule():
    t = steps_to_frame(clean_orders(hand_frame(), BASE_MAP).steps)
    assert list(t.columns) == ["Step", "Rule", "Rows removed", "Why"]
    assert len(t) == 8
