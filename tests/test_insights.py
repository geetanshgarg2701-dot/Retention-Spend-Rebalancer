import json

import pandas as pd
import pytest

from src import insights as ins
from src.checker import check_text
from src.metrics import SEGMENT_ORDER, monthly_orders, retention_report

# Distinctive ids and values so a leak into a prompt is easy to spot.
ROWS = [
    ("cust-9001", "2024-01-10", 713.17), ("cust-9001", "2024-02-20", 50.0), ("cust-9001", "2024-04-05", 50.0),
    ("cust-9002", "2024-01-25", 40.0), ("cust-9002", "2024-01-30", 60.0),
    ("cust-9003", "2024-02-05", 80.0),
    ("cust-9004", "2024-02-15", 30.0), ("cust-9004", "2024-05-20", 70.0),
    ("cust-9005", "2024-05-10", 90.0), ("cust-9005", "2024-06-15", 10.0),
]
IDS = ["cust-9001", "cust-9002", "cust-9003", "cust-9004", "cust-9005"]


@pytest.fixture
def frame():
    df = pd.DataFrame(ROWS, columns=["customer_id", "order_date", "order_value"])
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


@pytest.fixture
def facts(frame):
    report = retention_report(frame, window_days=90, cost_to_win=100)
    return ins.build_facts(report, monthly_orders(frame), 90, 100)


SCENARIO = {
    "horizon_months": 12, "value_basis": "revenue", "shift_percent_of_budget": 10, "estimated_change_in_value": 4210,
    "estimate_range_low": 1105, "estimate_range_high": 7894, "chance_it_beats_today": 0.83, "simulations": 2000,
    "best_move_percent_of_budget": 16, "best_move_is_at_the_edge_of_what_was_tested": False,
}


# ----------------------------------------------------------------------- facts

def test_facts_are_aggregates_only(facts):
    text = json.dumps(facts)
    for leak in IDS + ["713.17", "2024-01-10", "2024-05-20"]:
        assert leak not in text, leak
    assert facts["orders"] == 10 and facts["customers"] == 5 and facts["first_month"] == "2024-01" and facts["last_month"] == "2024-06"
    assert [s["name"] for s in facts["segments"]] == SEGMENT_ORDER
    assert facts["funnel"][1] == {"label": "2 or more orders", "customers": 4, "share_of_customers": 0.8}


def test_facts_include_payback_only_when_a_cost_was_entered(frame):
    report = retention_report(frame, 90, cost_to_win=None)
    no_cost = ins.build_facts(report, monthly_orders(frame), 90, None)
    assert "payback" not in no_cost
    with_cost = ins.build_facts(retention_report(frame, 90, cost_to_win=100), monthly_orders(frame), 90, 100)
    # Month 0 revenue per customer is (713.17 + 100 + 80 + 30 + 90) / 5 = 202.6, which already covers a cost of 100.
    assert with_cost["payback"] == {"cost_to_win_one_customer": 100.0, "reached": True, "month": 0}


def test_scenario_facts_come_from_the_simulation():
    from src import scenario as sc

    inputs = sc.Inputs(budget=1000, acquisition_share=0.8, cost_to_win=50, cost_to_bring_back=20, value_new=100,
                       extra_orders=2, order_value=30, exponent=0.5)
    ranges = sc.Ranges((50, 50), (20, 20), (2, 2), (0.5, 0.5))
    sim = sc.simulate(inputs, ranges, draws=100)
    f = ins.scenario_facts(inputs, sim, 10, 12, "revenue")
    assert f["shift_percent_of_budget"] == 10 and f["estimated_change_in_value"] == round(sc.delta_value(inputs, 0.10))
    assert f["best_move_percent_of_budget"] == 16 and f["best_move_is_at_the_edge_of_what_was_tested"] is False
    assert f["simulations"] == 100 and f["chance_it_beats_today"] == 1.0


# ---------------------------------------------------------------- template text

def test_the_apps_own_summary_passes_the_same_checker(facts):
    for variant in (facts, {**facts, "scenario": SCENARIO}, {k: v for k, v in facts.items() if k != "payback"}):
        text = ins.template_summary(variant)
        result = check_text(text, variant, max_words=ins.SUMMARY_MAX_WORDS)
        assert result.ok, result.reason()


def test_the_apps_summary_content(facts):
    text = ins.template_summary({**facts, "scenario": SCENARIO})
    assert "10 orders from 5 customers, from 2024-01 to 2024-06" in text
    assert "80.0% of customers ordered more than once" in text
    assert "moving 10% of the budget to keeping customers is estimated to change value by 4,210" in text
    assert "an estimate that depends on your assumptions" in text


def test_the_apps_own_ideas_pass_the_checker():
    for segment, ideas in ins.TEMPLATE_IDEAS.items():
        for idea in ideas:
            assert check_text(idea, {}, max_words=ins.IDEA_MAX_WORDS).ok, (segment, idea)
    assert set(ins.TEMPLATE_IDEAS) == set(SEGMENT_ORDER) == set(ins.SEGMENT_DESCRIPTIONS)


# ------------------------------------------------------------------ AI summary

GOOD = "Your file has 10 orders from 5 customers. 80% of customers ordered more than once."


def fake(reply):
    def call(prompt):
        call.prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    call.prompts = []
    return call


def test_a_checked_ai_summary_is_used(facts):
    ai = fake(GOOD)
    out = ins.generate_summary(facts, ai)
    assert out.source == "ai" and out.text == GOOD and "checked against your results" in out.note
    assert len(ai.prompts) == 1


def test_code_fences_around_the_reply_are_removed(facts):
    assert ins.generate_summary(facts, fake("```\n" + GOOD + "\n```")).text == GOOD


@pytest.mark.parametrize("reply, fragment", [
    ("Revenue grew 18% last year.", "18%"),
    ("About two thirds of customers came back.", "spelled-out numbers"),
    ("This will increase your revenue.", "too certain"),
    ("word " * 200, "too long"),
    ("", "empty answer"),
])
def test_a_bad_ai_summary_is_replaced_by_the_apps_own(facts, reply, fragment):
    out = ins.generate_summary(facts, fake(reply))
    assert out.source == "app" and out.text == ins.template_summary(facts)
    assert fragment in out.note and "discarded" in out.note


def test_ai_off_and_ai_failures_fall_back_without_a_crash(facts):
    off = ins.generate_summary(facts, None)
    assert off.source == "app" and "AI is off" in off.note
    quota = ins.generate_summary(facts, fake(RuntimeError("429 RESOURCE_EXHAUSTED")))
    assert quota.source == "app" and "limit may be used up" in quota.note
    assert "429" not in quota.note and "RESOURCE_EXHAUSTED" not in quota.note  # the raw error is not shown


def test_the_summary_prompt_carries_the_rules_and_only_the_facts(facts):
    prompt = ins.summary_prompt(facts)
    assert "Never calculate anything new" in prompt and "Never write a number as a word" in prompt
    assert "FACTS as JSON" in prompt and json.dumps(facts["orders"]) in prompt
    for leak in IDS + ["713.17", "2024-01-10"]:
        assert leak not in prompt


# ---------------------------------------------------------------- segment ideas

def ideas_json(**overrides):
    base = {name: [f"Try a gentle message for {name} customers."] for name in SEGMENT_ORDER}
    base.update(overrides)
    return json.dumps(base)


@pytest.mark.parametrize("reply", [
    "not json", "[]", "{}", '{"Champions": "a string"}', '{"Nobody": ["x"]}', '{"Champions": []}',
    '{"Champions": ["a", "b", "c", "d", "e"]}', '{"Champions": [1]}', '{"Champions": [""]}', None,
])
def test_parse_ideas_rejects_anything_unexpected(reply):
    assert ins.parse_ideas(reply) is None


def test_parse_ideas_accepts_a_subset_of_segments_and_fences():
    parsed = ins.parse_ideas("```json\n" + json.dumps({"Loyal": [" Reward them. "]}) + "\n```")
    assert parsed == {"Loyal": ["Reward them."]}


def test_good_ai_ideas_are_used_for_every_segment(facts):
    ai = fake(ideas_json())
    out = ins.generate_ideas(facts["segments"], ai)
    assert set(out.source.values()) == {"ai"} and out.dropped == 0
    assert out.ideas["Lapsed"] == ["Try a gentle message for Lapsed customers."]
    assert "ideas to test, not predictions" in out.note


def test_an_idea_with_an_invented_figure_is_dropped_and_the_rest_kept(facts):
    reply = ideas_json(Loyal=["Offer a reward.", "Give them 25% off every order."])
    out = ins.generate_ideas(facts["segments"], fake(reply))
    assert out.ideas["Loyal"] == ["Offer a reward."] and out.dropped == 1 and "1 idea did not pass" in out.note


def test_a_segment_with_no_passing_idea_gets_the_apps_own(facts):
    out = ins.generate_ideas(facts["segments"], fake(ideas_json(Champions=["Give them 99% off."])))
    assert out.ideas["Champions"] == ins.TEMPLATE_IDEAS["Champions"] and out.source["Champions"] == "app"
    assert out.source["Loyal"] == "ai"


def test_ideas_fall_back_on_bad_format_errors_and_ai_off(facts):
    bad = ins.generate_ideas(facts["segments"], fake("nonsense"))
    assert bad.ideas == ins.template_ideas().ideas and "not in the expected format" in bad.note
    err = ins.generate_ideas(facts["segments"], fake(RuntimeError("503 timed out")))
    assert "did not answer in time" in err.note
    assert ins.generate_ideas(facts["segments"], None).note.startswith("AI is off")


def test_the_ideas_prompt_describes_segments_without_customer_data(facts):
    prompt = ins.ideas_prompt(facts["segments"])
    assert "bought recently and often" in prompt and "Do not name any customer" in prompt
    for leak in IDS + ["713.17"]:
        assert leak not in prompt


# ---------------------------------------------------------- budget and errors

def test_the_call_budget_counts_and_stops():
    budget = ins.CallBudget(limit=2)
    ai = ins.with_budget(lambda prompt: "ok", budget)
    assert ai("a") == "ok" and ai("b") == "ok" and budget.used == 2 and budget.left == 0
    with pytest.raises(ins.AICapReached, match="used its 2 AI calls"):
        ai("c")
    assert budget.used == 2  # a refused call is not counted


def test_hitting_the_cap_falls_back_to_the_apps_own_text(facts):
    budget = ins.CallBudget(limit=0)
    out = ins.generate_summary(facts, ins.with_budget(lambda p: GOOD, budget))
    assert out.source == "app" and "used its 0 AI calls" in out.note


@pytest.mark.parametrize("error, fragment", [
    (RuntimeError("429 Too Many Requests"), "limit may be used up"),
    (RuntimeError("quota exceeded"), "limit may be used up"),
    (RuntimeError("403 PERMISSION_DENIED"), "did not accept the key"),
    (RuntimeError("API key not valid"), "did not accept the key"),
    (TimeoutError("deadline exceeded"), "did not answer in time"),
    (ValueError("generate_content failed accurately"), "request failed"),  # words like generate and accurate are not quota errors
])
def test_friendly_errors_never_echo_the_raw_message(error, fragment):
    message = ins.friendly_error(error)
    assert fragment in message and str(error) not in message
