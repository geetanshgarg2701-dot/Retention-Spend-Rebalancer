"""AI-written summary and segment ideas, with the code in charge of every number.

Only aggregate facts that the code already calculated are ever sent to the model. No customer id,
email, order row or order value from the file is included. Every reply is checked by src.checker,
and anything that fails is replaced by text the app writes itself.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from src.checker import check_text
from src.metrics import SEGMENT_ORDER

AIFunction = Callable[[str], str]
DEFAULT_CALL_LIMIT = 10
SUMMARY_MAX_WORDS = 170
IDEA_MAX_WORDS = 40
IDEAS_PER_SEGMENT = 4

SEGMENT_DESCRIPTIONS = {
    "Champions": "bought recently and often",
    "Loyal": "buy fairly often and fairly recently",
    "New": "placed their first order recently",
    "Occasional": "bought recently but not often",
    "At risk": "used to buy often but have gone quiet",
    "Lapsed": "bought rarely and not recently",
}
TEMPLATE_IDEAS = {
    "Champions": ["Invite them to a loyalty list or early access to new products.", "Ask for reviews and referrals while they are happy."],
    "Loyal": ["Offer a small reward on the next order to keep the habit going.", "Show products that go with what they usually buy."],
    "New": ["Send a welcome message that suggests a sensible second purchase.", "Share what makes your store different in the first weeks."],
    "Occasional": ["Remind them of products that go with what they bought.", "Offer a reason to order sooner, such as free delivery on the next order."],
    "At risk": ["Send a personal message that says you have missed them.", "Offer help or a reason to come back, then watch who responds."],
    "Lapsed": ["Run a win back message with one clear offer.", "Stop contacting people who do not respond after a couple of attempts."],
}


# --------------------------------------------------------------- budget and errors

class AICapReached(RuntimeError):
    """The session has used all of its AI calls."""


@dataclass
class CallBudget:
    limit: int = DEFAULT_CALL_LIMIT
    used: int = 0

    @property
    def left(self) -> int:
        return max(0, self.limit - self.used)

    def spend(self) -> None:
        if self.used >= self.limit:
            raise AICapReached(f"This session has used its {self.limit} AI calls. Start again with a new file to reset.")
        self.used += 1


def with_budget(ai_fn: AIFunction, budget: CallBudget) -> AIFunction:
    def call(prompt: str) -> str:
        budget.spend()
        return ai_fn(prompt)

    return call


def friendly_error(err: Exception) -> str:
    """A plain explanation that never repeats the raw error, which could carry request details."""
    if isinstance(err, AICapReached):
        return str(err)
    text = str(err).lower()
    if "429" in text or "resource_exhausted" in text or "quota" in text or "rate limit" in text or "too many requests" in text:
        return "The free Gemini limit may be used up for now. Try again later. The rest of the app still works."
    if "401" in text or "403" in text or "permission" in text or "api key" in text or "api_key" in text:
        return "Gemini did not accept the key. Check the GEMINI_API_KEY setting."
    if "timeout" in text or "timed out" in text or "deadline" in text:
        return "Gemini did not answer in time. Try again."
    return "The AI request failed, so the app's own text is shown instead."


# ----------------------------------------------------------------------- facts

def _r(value: Optional[float], digits: int = 4) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def build_facts(report, monthly: pd.Series, window_days: int, cost_to_win: Optional[float],
                scenario: Optional[dict] = None) -> dict:
    """The only numbers that may be sent to the model. All of them were calculated by the code."""
    rep = report.repeat
    pooled = report.cohorts.average
    basis = "margin" if "margin_per_customer" in report.curve else "revenue"
    facts = {
        "orders": int(rep["orders"]),
        "customers": int(rep["customers"]),
        "first_month": str(monthly.index[0]),
        "last_month": str(monthly.index[-1]),
        "average_order_value": _r(rep["average_order_value"], 2),
        "repeat_customers": int(rep["repeat_customers"]),
        "repeat_rate": _r(rep["repeat_rate"]),
        "repeat_window_days": int(window_days),
        "repeat_in_window_rate": _r(rep["repeat_in_window_rate"]),
        "median_days_to_second_order": _r(rep["median_days_to_second"], 1),
        "return_next_month_rate": _r(pooled.iloc[1]) if len(pooled) > 1 else None,
        "value_basis": basis,
        "value_months": 12,
        "value_per_customer_first_12_months": _r(report.twelve_month, 2),
        "funnel": [
            {"label": f"{int(r.orders)} or more orders", "customers": int(r.customers), "share_of_customers": _r(r.share)}
            for r in report.funnel.itertuples()
        ],
        "segments": segment_facts(report),
    }
    if cost_to_win is not None:
        facts["payback"] = {
            "cost_to_win_one_customer": _r(cost_to_win, 2), "reached": bool(report.payback["reached"]),
            "month": report.payback["month"],
        }
    if scenario:
        facts["scenario"] = scenario
    return {k: v for k, v in facts.items() if v is not None}


def segment_facts(report) -> list[dict]:
    seg = report.segments
    return [
        {
            "name": name, "customers": int(seg.loc[name, "customers"]), "share_of_customers": _r(seg.loc[name, "share_of_customers"]),
            "average_orders": _r(seg.loc[name, "average_orders"], 2), "average_spend": _r(seg.loc[name, "average_spend"], 2),
            "share_of_revenue": _r(seg.loc[name, "share_of_revenue"]),
        }
        for name in SEGMENT_ORDER
    ]


def scenario_facts(inputs, sim, shift_pct: int, horizon: int, basis: str) -> dict:
    """The scenario numbers the summary may mention. They are estimates, and the summary must say so."""
    idx = int(round(shift_pct - sim.shifts[0] * 100))
    edges = (round(float(sim.shifts.min()) * 100), round(float(sim.shifts.max()) * 100))
    best = round(sim.best_median * 100)
    return {
        "horizon_months": int(horizon), "value_basis": basis, "shift_percent_of_budget": int(shift_pct),
        "estimated_change_in_value": round(float(sim.median[idx])), "estimate_range_low": round(float(sim.p10[idx])),
        "estimate_range_high": round(float(sim.p90[idx])), "chance_it_beats_today": _r(sim.prob_positive[idx], 2),
        "simulations": int(sim.draws), "best_move_percent_of_budget": int(best),
        "best_move_is_at_the_edge_of_what_was_tested": bool(best != 0 and best in edges),
    }


# ---------------------------------------------------------------------- summary

SUMMARY_RULES = (
    "You turn a list of verified points about an online store's orders into a short, friendly summary for its owner.\n"
    "Rules:\n"
    "- Use only the figures in verified_points and FACTS, copied exactly as written. Write percentages with a percent sign.\n"
    "- Do not calculate anything. No sums, differences, ratios, multiples, totals or counts of your own. Do not count the "
    "segments or the months.\n"
    "- Never write a number as a word. Do not use words such as two, three, half, double, twice, third or quarter. "
    "Write 33.4% and never a third. The word one is fine in ordinary phrases.\n"
    "- Do not use lists, headings or bullet points. Write short paragraphs of at most 140 words in all.\n"
    "- Start with the summary itself. No greeting, no title and no introduction.\n"
    "- Figures per customer are averages. Say on average or a typical customer, never each customer or every customer.\n"
    "- Write natural sentences. Never copy field names or labels from FACTS, such as share_of_customers_percent "
    "or cost_to_win_one_customer.\n"
    "- Describe what the orders show. Do not predict, promise or give causes. If there is a scenario, say it is an "
    "estimate that depends on assumptions.\n"
    "- You may reorder and combine the points and use friendlier wording, but every figure must stay exactly as written.\n"
)

PERCENT_KEYS = {
    "repeat_rate", "repeat_in_window_rate", "return_next_month_rate", "share_of_customers", "share_of_revenue",
    "chance_it_beats_today",
}


def model_facts(facts: dict) -> dict:
    """The facts as the model sees them. Shares are written as percentages under a name ending in percent,
    so the model copies 33.4 and has no raw decimal such as 0.3338 to copy."""
    def convert(node):
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key in PERCENT_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool):
                    out[f"{key}_percent"] = round(value * 100, 1)
                else:
                    out[key] = convert(value)
            return out
        if isinstance(node, list):
            return [convert(item) for item in node]
        return node

    return convert(facts)


def prompt_payload(facts: dict) -> dict:
    """Everything the model sees and everything its text is checked against: the facts as percentages,
    plus the app's own verified sentences."""
    payload = model_facts(facts)
    payload["verified_points"] = summary_points(facts)
    return payload


def summary_prompt(facts: dict, problem: Optional[str] = None) -> str:
    text = SUMMARY_RULES + "\nFACTS as JSON, including verified_points:\n" + json.dumps(prompt_payload(facts), ensure_ascii=True, sort_keys=True)
    if problem:
        text += (
            f"\n\nYour last answer was rejected because it had {problem}. Write the summary again and fix that. "
            "Copy figures exactly from verified_points and keep to every rule above."
        )
    return text


def template_summary(facts: dict) -> str:
    """The summary the app writes itself. It uses only facts, so it passes the same checker."""
    return " ".join(summary_points(facts))


def summary_points(facts: dict) -> list[str]:
    """The app's own sentences about the results, one point each. They are the verified material the AI rewords."""
    parts = [
        f"Your file has {facts['orders']:,} orders from {facts['customers']:,} customers, from {facts['first_month']} to {facts['last_month']}."
    ]
    sentence = f"{facts['repeat_rate']:.1%} of customers ordered more than once"
    if "median_days_to_second_order" in facts:
        sentence += f", and the middle gap to a second order was {facts['median_days_to_second_order']:.0f} days"
    parts.append(sentence + ".")
    if "repeat_in_window_rate" in facts:
        parts.append(f"{facts['repeat_in_window_rate']:.1%} ordered again within {facts['repeat_window_days']} days of their first order.")
    if "value_per_customer_first_12_months" in facts:
        parts.append(
            f"A customer brought in {facts['value_per_customer_first_12_months']:,.0f} in {facts['value_basis']} over their first "
            f"{facts['value_months']} months, counting only customers who have had that long."
        )
    biggest = max(facts["segments"], key=lambda s: s["customers"])
    parts.append(
        f"The largest segment is {biggest['name']}, with {biggest['customers']:,} customers, "
        f"{biggest['share_of_customers']:.0%} of all customers."
    )
    pay = facts.get("payback")
    if pay:
        parts.append(
            f"Payback against your cost of {pay['cost_to_win_one_customer']:,.2f} came in month {pay['month']}."
            if pay["reached"] else
            f"Customers have not paid back your cost of {pay['cost_to_win_one_customer']:,.2f} within the months in this file."
        )
    sc = facts.get("scenario")
    if sc:
        move = sc["shift_percent_of_budget"]
        if move:
            toward = "to keeping customers" if move > 0 else "to winning customers"
            parts.append(
                f"Under your assumptions, moving {abs(move)}% of the budget {toward} is estimated to change value by "
                f"{sc['estimated_change_in_value']:,} over {sc['horizon_months']} months, with a range of "
                f"{sc['estimate_range_low']:,} to {sc['estimate_range_high']:,}. This is an estimate that depends on your assumptions."
            )
    return parts


@dataclass
class TextResult:
    text: str
    source: str  # "ai" or "app"
    note: str = ""


def _clean_reply(reply: str) -> str:
    text = str(reply).strip()
    fenced = re.fullmatch(r"```(?:\w+)?\s*(.*?)\s*```", text, flags=re.S)
    return fenced.group(1).strip() if fenced else text


def generate_summary(facts: dict, ai_fn: Optional[AIFunction], retries: int = 1) -> TextResult:
    """An AI summary if the model answers and every figure checks out, otherwise the app's own summary.

    If a check fails, the model is told what was wrong and may try again, up to retries more times.
    """
    fallback = template_summary(facts)
    if ai_fn is None:
        return TextResult(fallback, "app", "AI is off, so this summary was written by the app from your results.")
    payload = prompt_payload(facts)
    problem: Optional[str] = None
    for attempt in range(retries + 1):
        try:
            reply = ai_fn(summary_prompt(facts, problem))
        except Exception as err:
            return TextResult(fallback, "app", friendly_error(err))
        text = _clean_reply(reply)
        result = check_text(text, payload, max_words=SUMMARY_MAX_WORDS)
        if text and result.ok:
            note = "Written by AI. Every figure was checked against your results."
            return TextResult(text, "ai", note + (" It passed on the second try." if attempt else ""))
        problem = result.reason() if text else "an empty answer"
    return TextResult(fallback, "app", f"The AI wrote {problem}, so it was discarded and the app's own summary is shown.")


# ---------------------------------------------------------------- segment ideas

def ideas_prompt(segments: list[dict]) -> str:
    described = [{**s, "description": SEGMENT_DESCRIPTIONS[s["name"]]} for s in segments]
    return (
        "You suggest marketing ideas for groups of customers of an online store.\n"
        "For each segment in FACTS, give 2 or 3 concrete actions the owner could try.\n"
        "Rules:\n"
        "- Each idea is one sentence of at most 30 words.\n"
        "- Do not predict results or promise outcomes. These are ideas to test.\n"
        "- Do not include a figure unless it appears in FACTS. Write figures in digits.\n"
        "- Do not introduce numbers of your own, such as day counts, discount sizes, order counts or thresholds.\n"
        "- Never write a number as a word. The word one is fine.\n"
        "- Do not name any customer.\n"
        'Reply with JSON only: an object whose keys are the segment names exactly as in FACTS and whose values are lists of strings.\n\n'
        "FACTS as JSON:\n" + json.dumps(described, ensure_ascii=True, sort_keys=True)
    )


def parse_ideas(reply: object) -> Optional[dict[str, list[str]]]:
    """Strict parse. None on anything unexpected."""
    if not isinstance(reply, str):
        return None
    body = _clean_reply(reply)
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    out: dict[str, list[str]] = {}
    for name, ideas in data.items():
        if name not in SEGMENT_ORDER or not isinstance(ideas, list) or not 1 <= len(ideas) <= IDEAS_PER_SEGMENT:
            return None
        if not all(isinstance(i, str) and i.strip() for i in ideas):
            return None
        out[name] = [i.strip() for i in ideas]
    return out


@dataclass
class IdeasResult:
    ideas: dict[str, list[str]]
    source: dict[str, str]  # per segment, "ai" or "app"
    note: str = ""
    dropped: int = 0


def template_ideas() -> IdeasResult:
    return IdeasResult({s: list(TEMPLATE_IDEAS[s]) for s in SEGMENT_ORDER}, {s: "app" for s in SEGMENT_ORDER},
                       "AI is off, so these are the app's own starting ideas.")


def generate_ideas(segments: list[dict], ai_fn: Optional[AIFunction]) -> IdeasResult:
    """AI ideas that pass the checker, with the app's own ideas for any segment that has none left."""
    base = template_ideas()
    if ai_fn is None:
        return base
    try:
        reply = ai_fn(ideas_prompt(segments))
    except Exception as err:
        base.note = friendly_error(err)
        return base
    parsed = parse_ideas(reply)
    if parsed is None:
        base.note = "The AI reply was not in the expected format, so the app's own ideas are shown."
        return base
    ideas: dict[str, list[str]] = {}
    source: dict[str, str] = {}
    dropped = 0
    for name in SEGMENT_ORDER:
        kept = []
        for idea in parsed.get(name, []):
            if check_text(idea, segments, max_words=IDEA_MAX_WORDS).ok:
                kept.append(idea)
            else:
                dropped += 1
        ideas[name] = kept or list(TEMPLATE_IDEAS[name])
        source[name] = "ai" if kept else "app"
    note = "Ideas written by AI. Every figure was checked against your results. These are ideas to test, not predictions."
    if dropped:
        note += f" {dropped} idea{'s' if dropped != 1 else ''} did not pass the check and {'were' if dropped != 1 else 'was'} left out."
    return IdeasResult(ideas, source, note, dropped)
