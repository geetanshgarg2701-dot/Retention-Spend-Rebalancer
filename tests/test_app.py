from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.sample_data import generate_orders

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def no_ai_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


def fresh():
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    assert not at.exception
    return at


def test_starts_on_the_load_stage_with_privacy_and_synthetic_labels():
    at = fresh()
    assert at.button(key="load_sample") is not None
    text = " ".join(c.value for c in at.caption)
    assert "not stored" in text and "Synthetic" in text


def test_synthetic_sample_runs_through_all_three_stages():
    at = fresh()
    at.button(key="load_sample").click().run()
    assert not at.exception
    assert at.session_state["stage"] == 2
    picks = {s.label: s.value for s in at.selectbox if s.key and s.key.startswith("map_")}
    assert picks["Customer id, required"] == "Email"
    assert picks["Order value, required"] == "Line Total"
    assert picks["Order id"] == "Order Number"
    assert any("AI matching is off" in c.value for c in at.caption)
    assert at.toggle(key="use_ai").disabled

    at.button(key="confirm_columns").click().run()
    assert not at.exception
    assert at.session_state["stage"] == 3
    _, truth = generate_orders()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Orders"] == f"{truth['valid_orders']:,}"
    assert metrics["Customers"] == f"{truth['valid_customers']:,}"
    assert len(at.dataframe) >= 2  # steps table and preview
    assert at.session_state["clean"].stats["orders"] == truth["valid_orders"]


def test_missing_required_column_blocks_the_confirm_button():
    at = fresh()
    at.button(key="load_sample").click().run()
    key = next(s.key for s in at.selectbox if s.label == "Customer id, required")
    at.selectbox(key=key).select("No column").run()
    assert at.button(key="confirm_columns").disabled
    assert any("Customer id needs a column" in e.value for e in at.error)


def test_same_column_for_two_fields_blocks_the_confirm_button():
    at = fresh()
    at.button(key="load_sample").click().run()
    key = next(s.key for s in at.selectbox if s.label == "Order date, required")
    at.selectbox(key=key).select("Email").run()
    assert at.button(key="confirm_columns").disabled
    assert any("more than one field" in e.value for e in at.error)


def test_loading_a_different_file_resets_the_flow():
    at = fresh()
    at.button(key="load_sample").click().run()
    at.button(key="confirm_columns").click().run()
    assert at.session_state["stage"] == 3
    at.button(key="back_to_columns").click().run()
    at.button(key="back_to_load").click().run()
    assert "dataset" not in at.session_state
    assert "clean" not in at.session_state
    assert at.button(key="load_sample") is not None
