from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.sample_data import generate_orders

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def no_ai_key(monkeypatch, tmp_path):
    """Tests never see a real key and never call the model, even when a real .env exists."""
    from src import aiconfig

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(aiconfig, "ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setattr(aiconfig, "_secret", lambda name: None)


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


def to_scenario():
    at = to_results()
    at.button(key="to_scenario").click().run()
    assert not at.exception
    return at


def fill_scenario(at, budget=10000.0, share=80.0, cost_win=60.0, cost_back=25.0):
    at.number_input(key="opt_sample_s_budget").set_value(budget)
    at.number_input(key="opt_sample_s_share").set_value(share)
    at.number_input(key="opt_sample_s_cost_win").set_value(cost_win)
    at.number_input(key="opt_sample_s_cost_back").set_value(cost_back)
    at.run()
    assert not at.exception
    return at


def test_scenario_screen_asks_for_the_missing_inputs_first():
    at = to_scenario()
    assert at.session_state["stage"] == 5
    assert any("Budget scenario" in s.value for s in at.subheader)
    assert any("Enter the budget" in i.value and "the cost to bring a customer back" in i.value for i in at.info)
    assert not any(m.label == "Estimated change in value" for m in at.metric)
    at.number_input(key="opt_sample_s_budget").set_value(10000.0).run()
    note = next(i.value for i in at.info if i.value.startswith("Enter "))
    assert "the budget" not in note and "today's share" in note


def test_scenario_results_match_an_independent_run_of_the_model():
    from src import scenario as sc

    at = fill_scenario(to_scenario())
    frame = at.session_state["clean"].frame
    obs = sc.observed_inputs(frame, 12, None)
    inputs = sc.Inputs(budget=10000, acquisition_share=0.8, cost_to_win=60, cost_to_bring_back=25,
                       value_new=obs["value_new"], extra_orders=obs["extra_orders"], order_value=obs["order_value"])
    sim = sc.simulate(inputs, sc.ranges_from_pct(inputs, 0.25))
    low, _ = sc.allowed_shift_pct(0.8)
    best = max(low, min(50, round(sim.best_median * 100)))
    idx = best - low
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Estimated change in value"] == f"{sim.median[idx]:+,.0f}"
    assert metrics["Chance it beats today's split"] == f"{sim.prob_positive[idx]:.0%}"
    assert at.slider[0].value == best  # the slider starts at the best move found
    text = " ".join(m.value for m in at.markdown)
    assert "estimate" in text.lower() and "not a forecast" in text


def test_scenario_screen_labels_everything_as_an_estimate_and_lists_assumptions():
    at = fill_scenario(to_scenario())
    text = " ".join(m.value for m in at.markdown)
    assert "Assumptions behind these estimates" in text
    assert any(d.value is not None for d in at.dataframe)
    sources = at.dataframe[-1].value["Source"].tolist()
    assert sources.count("You entered it") == 4 and "Observed in your orders" in sources
    assert any("cannot show whether retention spend works" in m.value for m in at.markdown)


def test_moving_the_slider_changes_the_estimate_without_errors():
    at = fill_scenario(to_scenario())
    slider = at.slider[0]
    before = {m.label: m.value for m in at.metric}["Estimated change in value"]
    slider.set_value(0).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Estimated change in value"] == "+0" and metrics["Chance it beats today's split"] == "0%"
    assert before != "+0"
    assert any("Keeping today's split is the baseline" in m.value for m in at.markdown)


def test_changing_assumptions_changes_the_answer():
    at = fill_scenario(to_scenario())
    first = {m.label: m.value for m in at.metric}["Estimated change in value"]
    at.number_input(key="opt_sample_s_exponent").set_value(1.0).run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Estimated change in value"] != first
    at.number_input(key="opt_sample_s_extra").set_value(0.0).run()
    assert not at.exception  # zero extra orders is allowed, and retention is then worth nothing


def test_cost_to_win_is_prefilled_from_the_results_screen_and_inputs_survive_going_back():
    at = to_results()
    at.number_input(key="opt_sample_cost").set_value(45.0).run()
    at.button(key="to_scenario").click().run()
    assert at.number_input(key="opt_sample_s_cost_win").value == 45.0
    at.number_input(key="opt_sample_s_budget").set_value(8000.0).run()
    at.button(key="back_to_results").click().run()
    at.button(key="to_scenario").click().run()
    assert at.number_input(key="opt_sample_s_budget").value == 8000.0


def test_a_new_file_clears_the_scenario_inputs():
    at = fill_scenario(to_scenario())
    at.button(key="back_to_results").click().run()
    at.button(key="back_to_review").click().run()
    at.button(key="back_to_columns").click().run()
    at.button(key="back_to_load").click().run()
    assert "scenario_inputs" not in at.session_state


class FakeAI:
    """Answers by the kind of prompt, and records every prompt so tests can check what would have been sent."""

    def __init__(self):
        self.prompts = []
        self.summary = None
        self.ideas = None
        self.sql = None

    def __call__(self, prompt):
        import json
        from src.metrics import SEGMENT_ORDER

        self.prompts.append(prompt)
        if "verified points" in prompt:
            facts = json.loads(prompt.split("including verified_points:\n", 1)[1].split("\n\nYour last answer", 1)[0])
            return self.summary or f"Your file has {facts['orders']:,} orders from {facts['customers']:,} customers."
        if "marketing ideas" in prompt:
            return self.ideas or json.dumps({n: [f"Try a gentle message for the {n} group."] for n in SEGMENT_ORDER})
        if "DuckDB SQL" in prompt:
            return self.sql or json.dumps({"title": "Order count", "sql": "SELECT count(*) AS n FROM orders"})
        return "{}"  # the column matching prompt: no suggestions


@pytest.fixture
def fake_ai(monkeypatch):
    ai = FakeAI()
    monkeypatch.setattr("src.aiconfig.ai_available", lambda: True)
    monkeypatch.setattr("src.mapper.gemini_ai_function", lambda json_mode=True: ai)
    return ai


def to_insights():
    at = fill_scenario(to_scenario())
    at.button(key="to_insights").click().run()
    assert not at.exception
    return at


def insight_prompts(ai):
    return [p for p in ai.prompts if "verified points" in p or "marketing ideas" in p or "DuckDB SQL" in p]


def test_insights_screen_works_with_ai_off_and_still_has_summary_ideas_and_questions():
    at = to_insights()
    assert at.session_state["stage"] == 6
    assert any("Insights" in s.value for s in at.subheader)
    assert any("AI is off because no Gemini key is set" in c.value for c in at.caption)
    assert at.button(key="gen_summary").disabled and at.button(key="gen_ideas").disabled and at.button(key="run_ask").disabled
    text = " ".join(m.value for m in at.markdown)
    assert "Your file has" in text and "Written by the app from your results." in " ".join(c.value for c in at.caption)
    assert "Champions" in text and "ideas to test, not predictions" in " ".join(c.value for c in at.caption)


def test_the_ideas_tab_does_not_say_ai_is_off_when_ai_is_available(fake_ai):
    at = to_insights()
    captions = " ".join(c.value for c in at.caption)
    assert "Choose Get AI ideas for ideas written by AI" in captions
    assert "AI is off, so these are the app's own starting ideas" not in captions
    at.button(key="gen_ideas").click().run()
    assert any("Ideas written by AI" in c.value for c in at.caption)


def test_a_ready_made_question_runs_without_ai():
    at = to_insights()
    at.selectbox(key="ins_preset").select("Orders and revenue by month")
    at.button(key="run_preset").click().run()
    assert not at.exception and not at.error
    table = at.dataframe[-1].value
    assert list(table.columns) == ["month", "orders", "revenue"] and int(table["orders"].sum()) == at.session_state["clean"].stats["orders"]
    assert any("computed by the database" in c.value for c in at.caption)


def test_an_ai_summary_is_shown_after_it_passes_the_check_and_is_not_asked_twice(fake_ai):
    at = to_insights()
    assert not at.button(key="gen_summary").disabled
    at.button(key="gen_summary").click().run()
    assert not at.exception
    orders = at.session_state["clean"].stats["orders"]
    assert any(f"Your file has {orders:,} orders" in m.value for m in at.markdown)
    assert any("Every figure was checked" in c.value for c in at.caption)
    calls = len(insight_prompts(fake_ai))
    at.run()  # a plain rerun reuses the saved summary
    assert len(insight_prompts(fake_ai)) == calls == 1
    assert at.session_state["ai_budget"].used == 1


def test_an_ai_summary_with_an_invented_figure_is_discarded_and_the_app_text_is_shown(fake_ai):
    fake_ai.summary = "Revenue grew 999% last year, and customers will definitely return."
    at = to_insights()
    at.button(key="gen_summary").click().run()
    assert not at.exception
    assert any("discarded" in c.value for c in at.caption)
    assert not any("999" in m.value for m in at.markdown)
    assert any("Your file has" in m.value for m in at.markdown)


def test_ai_ideas_are_checked_and_bad_ones_are_left_out(fake_ai):
    import json
    from src.metrics import SEGMENT_ORDER

    ideas = {n: ["Offer a small thank you."] for n in SEGMENT_ORDER}
    ideas["Loyal"] = ["Offer a small thank you.", "Give them 77% off every order."]
    fake_ai.ideas = json.dumps(ideas)
    at = to_insights()
    at.button(key="gen_ideas").click().run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Offer a small thank you." in text and "77%" not in text
    assert any("did not pass the check" in c.value for c in at.caption)


def test_asking_your_own_question_runs_a_checked_query_locally(fake_ai):
    at = to_insights()
    at.text_input(key="ins_question").set_value("How many orders are there?").run()
    at.button(key="run_ask").click().run()
    assert not at.exception and not at.error
    assert at.dataframe[-1].value["n"].tolist() == [at.session_state["clean"].stats["orders"]]
    assert any("Order count" in m.value for m in at.markdown)
    assert any("SELECT count(*)" in c.value for c in at.code)


def test_a_dangerous_ai_query_is_refused_with_a_plain_message(fake_ai):
    import json

    fake_ai.sql = json.dumps({"title": "Oops", "sql": "DROP TABLE orders"})
    at = to_insights()
    at.text_input(key="ins_question").set_value("Delete everything").run()
    at.button(key="run_ask").click().run()
    assert not at.exception
    assert any("Only SELECT queries are allowed" in e.value for e in at.error)
    # The data is untouched, and the next ready-made question still works.
    at.button(key="run_preset").click().run()
    assert not at.error and at.dataframe[-1].value is not None


def test_no_customer_data_ever_appears_in_a_prompt(fake_ai):
    at = to_insights()
    at.button(key="gen_summary").click().run()
    at.button(key="gen_ideas").click().run()
    at.text_input(key="ins_question").set_value("Which month had the most orders?").run()
    at.button(key="run_ask").click().run()
    assert len(insight_prompts(fake_ai)) == 3
    everything = "\n".join(fake_ai.prompts)  # includes the earlier column matching prompt
    for leak in ("@example.com", "customer0", "Customer 0", "555-01"):  # emails, names and phones never go out
        assert leak not in everything, leak
    # The Insights prompts carry calculated figures and column names only. Not even product names or order numbers.
    for prompt in insight_prompts(fake_ai):
        for leak in ("Sample item", "#10", "#37", "customer0", "Customer 0", "@"):
            assert leak not in prompt, leak


def test_the_session_call_cap_disables_the_ai_buttons(fake_ai):
    from src import insights as ins

    at = to_insights()
    at.session_state["ai_budget"] = ins.CallBudget(limit=1, used=1)
    at.run()
    assert at.button(key="gen_summary").disabled and at.button(key="gen_ideas").disabled and at.button(key="run_ask").disabled
    assert any("1 of 1" in c.value for c in at.caption)


def test_ai_failures_never_crash_the_screen(monkeypatch, fake_ai):
    def boom(prompt):
        if "verified points" in prompt:
            raise RuntimeError("429 RESOURCE_EXHAUSTED some-secret-detail")
        return fake_ai(prompt)

    monkeypatch.setattr("src.mapper.gemini_ai_function", lambda json_mode=True: boom)
    at = to_insights()
    at.button(key="gen_summary").click().run()
    assert not at.exception
    assert any("limit may be used up" in c.value for c in at.caption)
    assert not any("some-secret-detail" in c.value for c in at.caption) and not any("some-secret-detail" in m.value for m in at.markdown)


def test_a_new_file_clears_the_insights_state(fake_ai):
    at = to_insights()
    at.button(key="gen_summary").click().run()
    assert at.session_state["ai_budget"].used == 1
    for key in ("back_to_scenario", "back_to_results", "back_to_review", "back_to_columns", "back_to_load"):
        at.button(key=key).click().run()
    assert "ai_budget" not in at.session_state and "scenario_result" not in at.session_state
    assert "ins_summary" not in repr(at.session_state) and "ins_ideas" not in repr(at.session_state)


def count_calls(monkeypatch, target, name):
    """Wrap a function the app imports by name, and count how often the app calls it."""
    import importlib

    module = importlib.import_module(target)
    original = getattr(module, name)
    calls = []

    def wrapper(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return calls


def test_the_retention_report_is_not_recalculated_on_every_click(monkeypatch):
    calls = count_calls(monkeypatch, "src.metrics", "retention_report")
    at = to_results()
    assert len(calls) == 1
    at.run()
    at.run()
    assert len(calls) == 1  # plain reruns reuse the saved report
    at.selectbox(key="opt_sample_window").select(60).run()
    assert len(calls) == 2  # a changed input recalculates once
    at.number_input(key="opt_sample_cost").set_value(30.0).run()
    assert len(calls) == 3


def test_the_scenario_and_insights_screens_reuse_the_saved_report(monkeypatch):
    calls = count_calls(monkeypatch, "src.metrics", "retention_report")
    at = to_insights()
    assert len(calls) == 1  # calculated on the results screen, then reused on the insights screen
    at.button(key="back_to_scenario").click().run()
    at.button(key="back_to_results").click().run()
    assert len(calls) == 1


def test_cleaning_again_invalidates_the_saved_results(monkeypatch):
    calls = count_calls(monkeypatch, "src.metrics", "retention_report")
    at = to_results()
    assert len(calls) == 1
    at.button(key="back_to_review").click().run()
    at.button(key="back_to_columns").click().run()
    at.button(key="confirm_columns").click().run()
    at.button(key="to_results").click().run()
    assert at.session_state["clean_n"] == 2 and len(calls) == 2  # new cleaned data means a fresh report


def test_moving_the_scenario_slider_does_not_rerun_the_simulation(monkeypatch):
    calls = count_calls(monkeypatch, "src.scenario", "simulate")
    at = fill_scenario(to_scenario())
    assert len(calls) == 1
    at.slider[0].set_value(0).run()
    at.slider[0].set_value(5).run()
    assert len(calls) == 1
    at.number_input(key="opt_sample_s_exponent").set_value(0.9).run()
    assert len(calls) == 2  # a changed assumption simulates once more


def test_the_clean_csv_is_built_only_on_demand(monkeypatch):
    original = pd.DataFrame.to_csv
    built = []

    def spy(self, *args, **kwargs):
        built.append(len(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_csv", spy)
    at = fresh()
    at.button(key="load_sample").click().run()
    at.button(key="confirm_columns").click().run()
    assert at.session_state["stage"] == 3 and not at.exception
    at.run()
    assert built == []  # the review screen rendered more than once without building the file


def test_an_unexpected_error_shows_a_friendly_message_and_never_leaks_details(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("RSR_RAISE_ERRORS", "0")

    def explode(*args, **kwargs):
        raise RuntimeError("secret-detail-123 customer@example.com")

    monkeypatch.setattr("src.metrics.retention_report", explode)
    at = fresh()
    at.button(key="load_sample").click().run()
    at.button(key="confirm_columns").click().run()
    with caplog.at_level(logging.ERROR, logger="rsr"):
        at.button(key="to_results").click().run()
    assert not at.exception  # the app handled it, so no traceback reached the page
    assert any("Something went wrong while showing this screen" in e.value for e in at.error)
    page = " ".join(e.value for e in at.error) + " ".join(m.value for m in at.markdown)
    assert "secret-detail-123" not in page and "customer@example.com" not in page
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged and "screen 4" in logged
    assert "secret-detail-123" not in logged and "customer@example.com" not in logged
    at.button(key="error_reset").click().run()
    assert "dataset" not in at.session_state and at.button(key="load_sample") is not None


def test_real_errors_are_raised_in_tests_so_they_cannot_be_missed(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("visible in tests")

    monkeypatch.setattr("src.metrics.retention_report", explode)
    at = fresh()
    at.button(key="load_sample").click().run()
    at.button(key="confirm_columns").click().run()
    at.button(key="to_results").click().run()
    assert at.exception  # RSR_RAISE_ERRORS is on in the test suite


def test_the_shared_daily_ai_limit_pauses_ai_for_everyone_with_a_clear_message(monkeypatch, fake_ai):
    from src import insights as ins

    monkeypatch.setattr(ins, "GLOBAL_DAILY", ins.DailyBudget(limit=0))
    at = to_insights()
    assert any("shared AI limit for today has been reached" in c.value for c in at.caption)
    assert at.button(key="gen_summary").disabled and at.button(key="gen_ideas").disabled and at.button(key="run_ask").disabled
    assert insight_prompts(fake_ai) == []
    # Ready-made questions and the app's own summary still work.
    at.button(key="run_preset").click().run()
    assert not at.error and "Your file has" in " ".join(m.value for m in at.markdown)


def test_column_matching_also_counts_against_the_shared_daily_limit(monkeypatch, fake_ai):
    from src import insights as ins

    daily = ins.DailyBudget(limit=5)
    monkeypatch.setattr(ins, "GLOBAL_DAILY", daily)
    at = fresh()
    at.button(key="load_sample").click().run()
    assert not at.exception and daily.used == 1  # the AI column matching call was counted
    monkeypatch.setattr(ins, "GLOBAL_DAILY", ins.DailyBudget(limit=0))
    at2 = fresh()
    at2.button(key="load_sample").click().run()
    assert not at2.exception  # when the day is used up, matching falls back to the rules
    assert any("rules only" in w.value for w in at2.warning)


def test_the_public_settings_hide_the_toolbar_and_error_details():
    import tomllib

    with open(".streamlit/config.toml", "rb") as f:
        client = tomllib.load(f)["client"]
    assert client["toolbarMode"] == "viewer" and client["showErrorDetails"] == "none"


def test_the_privacy_note_says_what_happens_on_a_hosted_server():
    at = fresh()
    text = " ".join(c.value for c in at.caption)
    assert "held in the server's memory for the session only" in text and "does not write it to disk or a database" in text


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
