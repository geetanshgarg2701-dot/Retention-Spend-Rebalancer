import json

import pandas as pd
import pytest

from src.mapper import (
    build_ai_payload,
    build_ai_prompt,
    map_columns,
    mask_value,
    parse_ai_response,
    rule_based_map,
)

N = 60
STATUSES = ["paid", "paid", "refunded", "paid", "voided"]


def emails(i):
    return f"person{i % 25}@example.com"


def shopify_frame():
    return pd.DataFrame({
        "Name": [f"#{1000 + i}" for i in range(N)],
        "Email": [emails(i) for i in range(N)],
        "Financial Status": [STATUSES[i % 5] for i in range(N)],
        "Paid at": [f"2025-03-{1 + i % 28:02d} 10:00:00 +0000" for i in range(N)],
        "Fulfillment Status": ["fulfilled"] * N,
        "Accepts Marketing": ["yes", "no"] * (N // 2),
        "Currency": ["USD"] * N,
        "Subtotal": [f"{20 + i % 9}.00" for i in range(N)],
        "Shipping": ["5.00"] * N,
        "Taxes": ["1.50"] * N,
        "Total": [f"{26 + i % 9}.50" for i in range(N)],
        "Discount Amount": ["0.00"] * N,
        "Created at": [f"2025-03-{1 + i % 28:02d} 09:00:00 +0000" for i in range(N)],
        "Lineitem quantity": [str(1 + i % 3) for i in range(N)],
        "Lineitem name": [f"Item {i % 7}" for i in range(N)],
        "Billing Name": [f"Person {i % 25}" for i in range(N)],
        "Billing Phone": [f"555010{i % 25:02d}" for i in range(N)],
    })


def woo_frame():
    return pd.DataFrame({
        "Order ID": [str(5000 + i) for i in range(N)],
        "Order Number": [str(5000 + i) for i in range(N)],
        "Order Status": ["completed", "completed", "refunded", "processing", "cancelled"] * (N // 5),
        "Order Date": [f"2025-04-{1 + i % 28:02d}" for i in range(N)],
        "Customer Note": [""] * N,
        "First Name (Billing)": [f"First{i % 25}" for i in range(N)],
        "Last Name (Billing)": [f"Last{i % 25}" for i in range(N)],
        "Email (Billing)": [emails(i) for i in range(N)],
        "Order Subtotal Amount": [f"{30 + i % 9}.00" for i in range(N)],
        "Order Total Amount": [f"{36 + i % 9}.00" for i in range(N)],
        "Order Shipping Amount": ["6.00"] * N,
        "Cart Discount Amount": ["0.00"] * N,
        "Order Refund Amount": ["0.00"] * N,
        "Order Total Tax Amount": ["2.10"] * N,
        "Payment Method Title": ["Card"] * N,
    })


def uci_frame():
    return pd.DataFrame({
        "InvoiceNo": [str(536365 + i // 3) for i in range(N)],
        "StockCode": [f"85{i % 40:03d}A" for i in range(N)],
        "Description": [f"WHITE HANGING HEART {i % 11}" for i in range(N)],
        "Quantity": [str(1 + i % 6) for i in range(N)],
        "InvoiceDate": [f"12/{1 + i % 28}/2010 8:26" for i in range(N)],
        "UnitPrice": [f"{2 + (i % 5) * 0.55:.2f}" for i in range(N)],
        "CustomerID": [str(17850 + i % 20) for i in range(N)],
        "Country": ["United Kingdom"] * N,
    })


def headers(result):
    return {f: m.header for f, m in result.matches.items()}


# ---------------------------------------------------------------- rule-based

def test_shopify_style_headers():
    r = rule_based_map(shopify_frame())
    h = headers(r)
    assert h["customer_id"] == "Email"
    assert h["order_date"] == "Created at"
    assert h["order_value"] == "Total"
    assert h["order_status"] == "Financial Status"
    assert h["quantity"] == "Lineitem quantity"
    assert h["order_id"] is None
    assert r.matches["order_value"].confidence == "high"
    assert r.multiply_quantity is False
    assert r.warnings and "will not be multiplied" in r.warnings[0]


def test_woocommerce_style_headers():
    r = rule_based_map(woo_frame())
    h = headers(r)
    assert h["order_id"] == "Order ID"
    assert h["customer_id"] == "Email (Billing)"
    assert h["order_date"] == "Order Date"
    assert h["order_value"] == "Order Total Amount"
    assert h["order_status"] == "Order Status"
    assert r.missing_required() == []


def test_uci_style_headers_use_unit_price_and_quantity():
    r = rule_based_map(uci_frame())
    h = headers(r)
    assert h["customer_id"] == "CustomerID"
    assert h["order_date"] == "InvoiceDate"
    assert h["order_value"] == "UnitPrice"
    assert h["quantity"] == "Quantity"
    assert h["order_id"] == "InvoiceNo"
    assert h["order_status"] is None
    assert r.multiply_quantity is True


def test_customer_id_is_never_assigned_on_content_alone():
    df = pd.DataFrame({
        "col_a": [str(1000 + i % 20) for i in range(N)],
        "col_b": [f"2025-01-{1 + i % 28:02d}" for i in range(N)],
        "col_c": [f"{10 + i % 7}.00" for i in range(N)],
    })
    r = rule_based_map(df)
    assert r.matches["customer_id"].header is None
    assert r.matches["order_date"].header == "col_b"
    assert r.matches["order_date"].confidence == "low"
    assert r.missing_required() == ["customer_id"]


def test_long_unique_integers_do_not_look_like_money():
    df = pd.DataFrame({
        "Customer ID": [str(i % 20) for i in range(N)],
        "Date": [f"2025-01-{1 + i % 28:02d}" for i in range(N)],
        "Amount": [str(100000000 + i) for i in range(N)],
    })
    m = rule_based_map(df).matches["order_value"]
    assert m.confidence != "high"
    assert "long unique ids" in m.reason


def test_negative_tokens_block_wrong_fields():
    df = pd.DataFrame({
        "Customer Name": [f"A{i % 9}" for i in range(N)],
        "Shipping Date": [f"2025-01-{1 + i % 28:02d}" for i in range(N)],
        "Shipping Amount": ["5.00"] * N,
    })
    h = headers(rule_based_map(df))
    assert h["customer_id"] is None
    assert h["order_date"] is None
    assert h["order_value"] is None


def test_each_column_is_used_once():
    h = [v for v in headers(rule_based_map(woo_frame())).values() if v]
    assert len(h) == len(set(h))


def test_empty_frame_returns_no_matches():
    r = rule_based_map(pd.DataFrame())
    assert all(m.header is None for m in r.matches.values())
    assert r.missing_required() == ["customer_id", "order_date", "order_value"]


# ---------------------------------------------------------------- AI helpers

def test_mask_value_hides_emails_and_truncates():
    assert mask_value("jane.doe@shop.com") == "<email>"
    assert mask_value("Contact jane.doe@shop.com now") == "Contact <email> now"
    assert mask_value("x" * 100) == "x" * 40 + "..."


def test_payload_has_headers_and_at_most_three_masked_values():
    payload = build_ai_payload(shopify_frame())
    assert set(payload) == set(shopify_frame().columns)
    assert all(len(v) <= 3 for v in payload.values())
    assert payload["Email"] == ["<email>"]
    assert "@" not in build_ai_prompt(payload)


def test_parse_ai_response_accepts_valid_json_and_fences():
    hs = ["A", "B", "C"]
    body = {"customer_id": "A", "order_date": "B", "order_value": None}
    assert parse_ai_response(json.dumps(body), hs)["customer_id"] == "A"
    fenced = "```json\n" + json.dumps(body) + "\n```"
    parsed = parse_ai_response(fenced, hs)
    assert parsed["order_date"] == "B" and parsed["order_id"] is None


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"customer_id": "Missing header"}',
        '{"customer_id": "A", "order_date": "A"}',
        '{"customer_id": 5}',
        None,
    ],
)
def test_parse_ai_response_rejects_bad_output(text):
    assert parse_ai_response(text, ["A", "B"]) is None


# ------------------------------------------------------------ AI merge cases

def rules_answer(df):
    return {f: h for f, h in headers(rule_based_map(df)).items()}


def test_ai_agreement_gives_high_confidence():
    df = woo_frame()
    answer = rules_answer(df)
    r = map_columns(df, ai_fn=lambda prompt: json.dumps(answer))
    assert r.ai_used
    assert all(m.confidence == "high" for m in r.matches.values() if m.header)
    assert r.matches["order_value"].source == "both"
    assert not any("disagree" in w for w in r.warnings)


def test_ai_disagreement_gives_low_confidence_and_a_warning():
    df = woo_frame()
    answer = rules_answer(df)
    answer["order_value"] = "Order Subtotal Amount"
    r = map_columns(df, ai_fn=lambda prompt: json.dumps(answer))
    m = r.matches["order_value"]
    assert m.header == "Order Total Amount"
    assert m.alternative == "Order Subtotal Amount"
    assert m.confidence == "low"
    assert "disagree" in r.warnings[0] and "Order value" in r.warnings[0]


def test_ai_fills_a_gap_with_low_confidence():
    df = pd.DataFrame({
        "who": [f"c{i % 15}" for i in range(N)],
        "when": [f"2025-02-{1 + i % 28:02d}" for i in range(N)],
        "Order Total": [f"{10 + i % 5}.00" for i in range(N)],
    })
    assert rule_based_map(df).matches["customer_id"].header is None
    answer = {"customer_id": "who"}
    r = map_columns(df, ai_fn=lambda prompt: json.dumps(answer))
    m = r.matches["customer_id"]
    assert (m.header, m.confidence, m.source) == ("who", "low", "ai")


def test_malformed_ai_response_falls_back_to_rules():
    df = woo_frame()
    r = map_columns(df, ai_fn=lambda prompt: "Sorry, I cannot help with that.")
    assert not r.ai_used
    assert headers(r) == headers(rule_based_map(df))
    assert "rules only" in r.warnings[0]


def test_ai_function_that_raises_falls_back_to_rules():
    def boom(prompt):
        raise RuntimeError("network down")

    df = woo_frame()
    r = map_columns(df, ai_fn=boom)
    assert headers(r) == headers(rule_based_map(df))
    assert "rules only" in r.warnings[0]


def test_ai_never_sees_raw_emails():
    seen = []

    def spy(prompt):
        seen.append(prompt)
        return "{}"

    map_columns(shopify_frame(), ai_fn=spy)
    assert seen and "person1@example.com" not in seen[0]
    assert "<email>" in seen[0]
