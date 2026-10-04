"""Hand-checked retention metrics.

Ten orders from five customers. Every expected number below was worked out on
paper from this table, with the last order date being 2024-06-15, a leap year.

  A  2024-01-10  100   2024-02-20  50   2024-04-05  50     total 200, 3 orders
  B  2024-01-25   40   2024-01-30  60                      total 100, 2 orders
  C  2024-02-05   80                                       total  80, 1 order
  D  2024-02-15   30   2024-05-20  70                      total 100, 2 orders
  E  2024-05-10   90   2024-06-15  10                      total 100, 2 orders
"""
import numpy as np
import pandas as pd
import pytest

from src.metrics import (
    SEGMENT_ORDER,
    _score,
    assign_segment,
    cohort_retention,
    monthly_orders,
    order_count_funnel,
    payback,
    payback_progress,
    repeat_metrics,
    retention_report,
    rfm_table,
    segment_summary,
    twelve_month_value,
    value_curve,
)

ROWS = [
    ("A", "2024-01-10", 100), ("A", "2024-02-20", 50), ("A", "2024-04-05", 50),
    ("B", "2024-01-25", 40), ("B", "2024-01-30", 60),
    ("C", "2024-02-05", 80),
    ("D", "2024-02-15", 30), ("D", "2024-05-20", 70),
    ("E", "2024-05-10", 90), ("E", "2024-06-15", 10),
]


@pytest.fixture
def frame():
    df = pd.DataFrame(ROWS, columns=["customer_id", "order_date", "order_value"])
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


# ---------------------------------------------------------------- repeat rate

def test_repeat_metrics_match_the_hand_count(frame):
    r = repeat_metrics(frame, window_days=90)
    assert r["customers"] == 5 and r["orders"] == 10
    assert r["repeat_customers"] == 4 and r["repeat_rate"] == pytest.approx(0.8)  # all but C
    assert r["average_order_value"] == pytest.approx(58.0)  # 580 over 10 orders
    # Window cut-off is 2024-06-15 minus 90 days, which is 2024-03-17. A, B, C, D started before it.
    assert r["eligible_customers"] == 4
    # Days from first to second order: A 41, B 5, D 95, E 36. Within 90 days: A and B.
    assert r["repeat_in_window"] == 2 and r["repeat_in_window_rate"] == pytest.approx(0.5)
    assert r["median_days_to_second"] == pytest.approx(38.5)  # sorted 5, 36, 41, 95
    assert r["last_order_date"] == pd.Timestamp("2024-06-15")


def test_a_shorter_window_changes_the_eligible_group(frame):
    # 30 days: cut-off 2024-05-16, so A, B, C, D, still eligible, E started 05-10 so is eligible too.
    r = repeat_metrics(frame, window_days=30)
    assert r["eligible_customers"] == 5
    assert r["repeat_in_window"] == 1  # only B, 5 days. E is 36 days, A 41, D 95.
    assert r["repeat_in_window_rate"] == pytest.approx(0.2)


def test_window_rate_is_none_when_nobody_is_old_enough():
    df = pd.DataFrame({"customer_id": ["a", "b"], "order_date": pd.to_datetime(["2024-06-01", "2024-06-10"]),
                       "order_value": [5, 5]})
    r = repeat_metrics(df, window_days=90)
    assert r["eligible_customers"] == 0 and r["repeat_in_window_rate"] is None
    assert r["median_days_to_second"] is None


# -------------------------------------------------------------------- cohorts

def test_cohort_retention_matches_the_hand_count(frame):
    c = cohort_retention(frame)
    assert list(c.sizes.index) == ["2024-01", "2024-02", "2024-05"]
    assert list(c.sizes) == [2, 2, 1]
    assert c.months_observed == 6  # January to June
    nan = np.nan
    expected = pd.DataFrame(
        [[1, 0.5, 0, 0.5, 0, 0],       # Jan: A in Feb and Apr, B only in Jan
         [1, 0, 0, 0.5, 0, nan],       # Feb: D in May is month 3, June not yet observable for Feb+5
         [1, 1, nan, nan, nan, nan]],  # May: E in June is month 1
        index=["2024-01", "2024-02", "2024-05"], columns=range(6), dtype=float,
    )
    pd.testing.assert_frame_equal(c.retention, expected, check_names=False)
    # Pooled: month 1 is 2 of 5, month 2 is 0 of 4, month 3 is 2 of 4, month 5 is 0 of 2.
    assert list(c.average.round(6)) == [1.0, 0.4, 0.0, 0.5, 0.0, 0.0]
    assert c.last_month_partial is True  # the last order is on the 15th


def test_last_month_is_not_partial_when_the_data_ends_on_the_last_day():
    df = pd.DataFrame({"customer_id": ["a"], "order_date": pd.to_datetime(["2024-06-30"]), "order_value": [5]})
    assert cohort_retention(df).last_month_partial is False


# ------------------------------------------------------------------------ RFM

def test_rfm_matches_the_hand_count(frame):
    t = rfm_table(frame, window_days=90).set_index("customer_id")
    # Days from last order to 2024-06-15: A 71, B 137, C 131, D 26, E 0.
    assert t["recency_days"].to_dict() == {"A": 71, "B": 137, "C": 131, "D": 26, "E": 0}
    assert t["frequency"].to_dict() == {"A": 3, "B": 2, "C": 1, "D": 2, "E": 2}
    assert t["monetary"].to_dict() == {"A": 200, "B": 100, "C": 80, "D": 100, "E": 100}
    # Recency ranks from least to most recent: B, C, A, D, E, so scores 1 to 5.
    assert t["r_score"].to_dict() == {"B": 1, "C": 2, "A": 3, "D": 4, "E": 5}
    # Frequency and spend: C lowest, A highest, B D E tie in the middle at rank 3, score 3.
    assert t["f_score"].to_dict() == {"C": 1, "B": 3, "D": 3, "E": 3, "A": 5}
    assert t["m_score"].to_dict() == t["f_score"].to_dict()
    # E is new, its first order was 36 days before the end. A and D are loyal, B is at risk, C is lapsed.
    assert t["segment"].to_dict() == {"A": "Loyal", "B": "At risk", "C": "Lapsed", "D": "Loyal", "E": "New"}


def test_segment_summary_matches_the_hand_count(frame):
    s = segment_summary(rfm_table(frame))
    assert list(s.index) == SEGMENT_ORDER
    assert s["customers"].to_dict() == {
        "Champions": 0, "Loyal": 2, "New": 1, "Occasional": 0, "At risk": 1, "Lapsed": 1,
    }
    assert s.loc["Loyal", "average_orders"] == pytest.approx(2.5)
    assert s.loc["Loyal", "average_spend"] == pytest.approx(150)
    assert s.loc["Loyal", "share_of_customers"] == pytest.approx(0.4)
    assert s.loc["Loyal", "share_of_revenue"] == pytest.approx(300 / 580)
    assert s["share_of_customers"].sum() == pytest.approx(1.0)
    assert s["share_of_revenue"].sum() == pytest.approx(1.0)


@pytest.mark.parametrize(
    "r, f, new, expected",
    [
        (1, 1, True, "New"), (5, 5, True, "New"),
        (5, 5, False, "Champions"), (4, 4, False, "Champions"),
        (4, 3, False, "Loyal"), (3, 5, False, "Loyal"), (3, 3, False, "Loyal"),
        (2, 3, False, "At risk"), (1, 5, False, "At risk"),
        (2, 2, False, "Lapsed"), (1, 1, False, "Lapsed"),
        (3, 2, False, "Occasional"), (5, 1, False, "Occasional"),
    ],
)
def test_every_segment_rule(r, f, new, expected):
    assert assign_segment(r, f, new) == expected


def test_every_score_pair_lands_in_exactly_one_segment():
    names = {assign_segment(r, f, False) for r in range(1, 6) for f in range(1, 6)}
    assert names == set(SEGMENT_ORDER) - {"New"}


def test_scores_give_ties_the_same_score():
    s = _score(pd.Series([1, 1, 2, 2]))
    # Average ranks 1.5, 1.5, 3.5, 3.5 over 4, times 5, rounded up: 1.875 gives 2, 4.375 gives 5.
    assert list(s) == [2, 2, 5, 5]


# --------------------------------------------------------------------- funnel

def test_order_count_funnel_matches_the_hand_count(frame):
    f = order_count_funnel(frame)
    # Orders per customer: A 3, B 2, C 1, D 2, E 2. So 5 reach 1, 4 reach 2, 1 reaches 3, none reach 5.
    assert list(f["orders"]) == [1, 2, 3, 5]
    assert list(f["customers"]) == [5, 4, 1, 0]
    assert list(f["share"]) == pytest.approx([1.0, 0.8, 0.2, 0.0])
    assert pd.isna(f["share_of_previous"].iloc[0])  # nothing comes before the first step
    assert list(f["share_of_previous"].iloc[1:]) == pytest.approx([0.8, 0.25, 0.0])


def test_report_includes_the_funnel(frame):
    assert list(retention_report(frame).funnel["customers"]) == [5, 4, 1, 0]


# ------------------------------------------------------------- value and payback

def test_value_curve_matches_the_hand_count(frame):
    c = value_curve(frame)
    assert list(c["month"]) == [0, 1, 2, 3, 4, 5]
    # Month 5 can only use January customers, A and B. Month 2 onward drops E, month 4 keeps Jan and Feb.
    assert list(c["customers_observed"]) == [5, 5, 4, 4, 4, 2]
    # Cumulative revenue per customer: 400/5, 460/5, 360/4, 480/4, 480/4, 300/2.
    assert list(c["revenue_per_customer"].round(6)) == [80.0, 92.0, 90.0, 120.0, 120.0, 150.0]
    assert "margin_per_customer" not in c
    assert twelve_month_value(c) is None  # nobody has been observed for 12 months


def test_value_curve_with_margin(frame):
    c = value_curve(frame, margin_pct=50)
    assert list(c["margin_per_customer"].round(6)) == [40.0, 46.0, 45.0, 60.0, 60.0, 75.0]


@pytest.mark.parametrize("cost, month", [(100, 3), (120, 3), (121, 5), (80, 0), (150, 5), (151, None)])
def test_payback_on_revenue(frame, cost, month):
    p = payback(value_curve(frame), cost)
    assert p["basis"] == "revenue" and p["entered"] is True
    assert p["month"] == month and p["reached"] is (month is not None)


# Margin per customer at 50 percent is 40, 46, 45, 60, 60, 75 for months 0 to 5.
@pytest.mark.parametrize("cost, month", [(40, 0), (45, 1), (46, 1), (50, 3), (60, 3), (75, 5), (80, None)])
def test_payback_on_margin(frame, cost, month):
    p = payback(value_curve(frame, margin_pct=50), cost)
    assert p["basis"] == "margin" and p["month"] == month


def test_payback_without_a_cost_says_so(frame):
    p = payback(value_curve(frame), None)
    assert p == {"basis": "revenue", "reached": False, "month": None, "entered": False}


def test_payback_progress_matches_the_hand_count(frame):
    # Revenue per customer by month is 80, 92, 90, 120, 120, 150, so the best is 150.
    revenue = payback_progress(value_curve(frame), 200)
    assert revenue == {"basis": "revenue", "entered": True, "best_value": 150.0, "share": 0.75}
    assert payback_progress(value_curve(frame), 100)["share"] == 1.0  # capped, the cost is already covered
    assert payback_progress(value_curve(frame), 0)["share"] == 1.0
    margin = payback_progress(value_curve(frame, margin_pct=50), 100)  # best margin is 75
    assert margin["basis"] == "margin" and margin["best_value"] == 75.0 and margin["share"] == 0.75
    none = payback_progress(value_curve(frame), None)
    assert none["entered"] is False and none["share"] is None and none["best_value"] == 150.0
    with pytest.raises(ValueError, match="cannot be negative"):
        payback_progress(value_curve(frame), -1)


def test_monthly_orders_matches_the_hand_count(frame):
    m = monthly_orders(frame)
    # January 3 orders, February 3, March none, April 1, May 2, June 1. Ten in all.
    assert list(m.index) == ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
    assert list(m) == [3, 3, 0, 1, 2, 1]
    assert m.sum() == 10


def test_twelve_month_value_appears_when_observed():
    df = pd.DataFrame({
        "customer_id": ["a", "a", "b"],
        "order_date": pd.to_datetime(["2023-01-10", "2023-12-05", "2024-03-01"]),
        "order_value": [10, 20, 5],
    })
    c = value_curve(df)
    # Month 11 uses only a, whose cumulative revenue through December 2023 is 30.
    assert twelve_month_value(c) == pytest.approx(30.0)


@pytest.mark.parametrize("margin", [0, -5, 101])
def test_bad_margin_is_rejected(frame, margin):
    with pytest.raises(ValueError, match="margin"):
        value_curve(frame, margin_pct=margin)


def test_negative_cost_is_rejected(frame):
    with pytest.raises(ValueError, match="cannot be negative"):
        payback(value_curve(frame), -1)


# ------------------------------------------------------------------- the report

def test_report_ties_everything_together_and_warns(frame):
    r = retention_report(frame, window_days=90, cost_to_win=100)
    assert r.repeat["repeat_customers"] == 4
    assert r.payback["month"] == 3
    assert r.twelve_month is None
    text = " ".join(r.warnings)
    assert "Only 5 customers" in text and "looks incomplete" in text


def test_results_do_not_depend_on_row_order(frame):
    shuffled = frame.sample(frac=1, random_state=3).reset_index(drop=True)
    a, b = retention_report(frame), retention_report(shuffled)
    assert a.repeat == b.repeat
    pd.testing.assert_frame_equal(a.cohorts.retention, b.cohorts.retention)
    pd.testing.assert_frame_equal(a.curve, b.curve)
    pd.testing.assert_frame_equal(a.rfm.sort_values("customer_id").reset_index(drop=True),
                                  b.rfm.sort_values("customer_id").reset_index(drop=True))


def test_missing_columns_and_empty_input_raise_plain_errors(frame):
    with pytest.raises(ValueError, match="order_value"):
        repeat_metrics(frame.drop(columns="order_value"))
    with pytest.raises(ValueError, match="no orders"):
        repeat_metrics(frame.iloc[0:0])
