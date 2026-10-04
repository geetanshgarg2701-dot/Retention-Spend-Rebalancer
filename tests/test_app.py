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


def to_results():
    at = fresh()
    at.button(key="load_sample").click().run()
    at.button(key="confirm_columns").click().run()
    at.button(key="to_results").click().run()
    assert not at.exception
    return at


def test_results_screen_shows_every_section_and_labels_the_sample():
    at = to_results()
    assert at.session_state["stage"] == 4
    assert any("Synthetic" in i.value for i in at.info)
    labels = {m.label for m in at.metric}
    assert {"Customers who ordered again", "Median days to a second order", "Average order value",
            "Revenue per customer in the first 12 months", "Payback month"} <= labels
    assert any(l.startswith("Ordered again within 90 days") for l in labels)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Payback month"] == "Enter your cost"
    assert len(at.dataframe) >= 2  # cohort table and segment table
    assert any("Nothing is forecast" in m.value for m in at.markdown)


def test_each_stage_has_its_own_title_and_the_funnel_is_computed():
    at = fresh()
    assert any("Load your orders" in s.value for s in at.subheader)
    at.button(key="load_sample").click().run()
    assert any("Confirm columns" in s.value for s in at.subheader)
    at.button(key="confirm_columns").click().run()
    assert any("Review the cleaning" in s.value for s in at.subheader)
    at.button(key="to_results").click().run()
    assert not at.exception
    assert any("Retention results" in s.value for s in at.subheader)
    funnel = retention_report_for(at).funnel
    assert funnel["customers"].is_monotonic_decreasing and funnel["customers"].iloc[0] > 0


def retention_report_for(at):
    from src.metrics import retention_report

    return retention_report(at.session_state["clean"].frame)


def test_results_agree_with_the_metrics_module():
    from src.metrics import retention_report

    at = to_results()
    expected = retention_report(at.session_state["clean"].frame)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Customers who ordered again"] == f"{expected.repeat['repeat_rate']:.1%}"
    assert metrics["Average order value"] == f"{expected.repeat['average_order_value']:,.2f}"


def test_entering_a_cost_and_margin_changes_the_payback():
    from src.metrics import retention_report

    at = to_results()
    at.number_input(key="opt_sample_cost").set_value(20.0).run()
    assert not at.exception
    frame = at.session_state["clean"].frame
    expected = retention_report(frame, cost_to_win=20.0).payback
    assert expected["reached"]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Payback month"] == f"Month {expected['month']}"
    assert any("uses revenue because no margin was entered" in c.value for c in at.caption)

    at.number_input(key="opt_sample_margin").set_value(40.0).run()
    assert not at.exception
    margin_pay = retention_report(frame, cost_to_win=20.0, margin_pct=40.0).payback
    metrics = {m.label: m.value for m in at.metric}
    want = f"Month {margin_pay['month']}" if margin_pay["reached"] else "Not reached"
    assert metrics["Payback month"] == want


def test_changing_the_window_updates_the_label_and_going_back_keeps_inputs():
    at = to_results()
    at.selectbox(key="opt_sample_window").select(60).run()
    assert any(m.label.startswith("Ordered again within 60 days") for m in at.metric)
    at.button(key="back_to_review").click().run()
    assert at.session_state["stage"] == 3
    at.button(key="to_results").click().run()
    assert any(m.label.startswith("Ordered again within 60 days") for m in at.metric)


def test_a_new_file_clears_the_results_inputs():
    at = to_results()
    at.number_input(key="opt_sample_cost").set_value(20.0).run()
    at.button(key="back_to_review").click().run()
    at.button(key="back_to_columns").click().run()
    at.button(key="back_to_load").click().run()
    assert "retention_inputs" not in at.session_state


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
