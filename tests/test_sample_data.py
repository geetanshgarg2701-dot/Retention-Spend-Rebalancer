import pandas as pd
import pytest

from src.cleaning import clean_orders
from src.mapper import rule_based_map
from src.sample_data import SYNTHETIC_NOTICE, generate_orders, write_sample


@pytest.fixture(scope="module")
def sample():
    return generate_orders()


def read_back(df, tmp_path):
    path = tmp_path / "s.csv"
    df.to_csv(path, index=False)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_same_seed_gives_identical_output(sample):
    again, truth_again = generate_orders()
    pd.testing.assert_frame_equal(sample[0], again)
    assert sample[1] == truth_again


def test_a_different_seed_gives_different_output(sample):
    other, _ = generate_orders(seed=7)
    assert not other.equals(sample[0])


def test_size_and_span(sample):
    df, truth = sample
    assert truth["customers"] == 1500
    assert 2500 < truth["orders"] < 6000
    assert truth["rows"] == len(df) > truth["orders"]
    dates = pd.to_datetime(df["Created at"], errors="coerce", format="mixed", utc=True).dropna()
    assert (dates.max() - dates.min()).days > 600


def test_every_row_says_it_is_synthetic(sample):
    assert set(sample[0]["Notes"]) == {"Synthetic demo order"}
    assert "not a real business" in SYNTHETIC_NOTICE
    assert sample[0]["Email"].str.contains("@example.com").sum() > 0


def test_the_mess_is_present(sample):
    df, truth = sample
    created = df["Created at"]
    assert created.str.contains(r"UTC$").any() and created.str.contains(r"[+-]\d{4}$").any()
    assert created.str.contains("T.*Z$").any() and created.str.contains(r"^\d{2}/\d{2}/\d{4}").any()
    money = df["Line Total"]
    assert money.str.startswith("$").any() and money.str.contains(r"\d,\d{3}\.").any()
    assert df["Financial Status"].str.lower().isin({"refunded", "voided", "cancelled"}).any()
    assert (df["Email"] == "").any()
    for key in ("unreadable_date_orders", "zero_value_orders", "partial_refund_orders", "multi_line_orders"):
        assert truth[key] > 0, key
    assert df["Billing Name"].notna().all() and "Billing Phone" in df.columns


def test_mapper_finds_the_right_columns_on_the_messy_file(sample, tmp_path):
    h = rule_based_map(read_back(sample[0], tmp_path)).mapping()
    assert h["customer_id"] == "Email"
    assert h["order_date"] == "Created at"
    assert h["order_value"] == "Line Total"
    assert h["order_id"] == "Order Number"
    assert h["order_status"] == "Financial Status"
    assert "Billing Name" not in h.values() and "Fulfilled at" not in h.values()


def test_cleaning_matches_the_generator_truth(sample, tmp_path):
    raw = read_back(sample[0], tmp_path)
    truth = sample[1]
    mapping = rule_based_map(raw).mapping()
    result = clean_orders(raw, mapping)
    assert result.stats["orders"] == truth["valid_orders"]
    assert result.stats["customers"] == truth["valid_customers"]
    assert result.stats["total_revenue"] == pytest.approx(truth["valid_revenue"], abs=0.01)
    assert result.stats["dayfirst_used"] is False
    assert not any("Month first was assumed" in w for w in result.warnings)
    steps = {s.number: s.rows_removed for s in result.steps}
    assert all(steps[n] > 0 for n in (1, 2, 3, 5, 6, 7))
    assert steps[4] == 0 and steps[8] == 0


def test_partial_refunds_survive_cleaning(sample, tmp_path):
    raw = read_back(sample[0], tmp_path)
    partial = raw[raw["Financial Status"].str.lower() == "partially_refunded"]
    assert len(partial) > 0
    result = clean_orders(raw, rule_based_map(raw).mapping())
    assert set(partial["Order Number"]) & set(result.frame["order_id"])


def test_write_sample_refuses_to_overwrite(tmp_path):
    path = tmp_path / "out.csv"
    write_sample(path)
    with pytest.raises(FileExistsError, match="already exists"):
        write_sample(path)
    write_sample(path, overwrite=True)
    assert path.read_text(encoding="utf-8").startswith("Order Number,Email")
