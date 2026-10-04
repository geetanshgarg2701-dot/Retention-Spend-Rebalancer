"""Live check of the Week 4 AI features on the synthetic sample.

By default this is a dry run: it prints the exact prompts that would be sent and contacts nobody.
Add --send to make the calls, at most three, one per feature. The key is read from .env and is never printed.
    python scripts/2026-10-04-live-insights-check.py
    python scripts/2026-10-04-live-insights-check.py --send
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src import askdata, insights as ins  # noqa: E402
from src import scenario as sc  # noqa: E402
from src.checker import check_text  # noqa: E402
from src.cleaning import clean_orders  # noqa: E402
from src.mapper import gemini_ai_function, rule_based_map  # noqa: E402
from src.metrics import monthly_orders, retention_report  # noqa: E402

QUESTION = "Which month had the most orders?"
COST_TO_WIN = 60.0  # an illustrative figure for this check on synthetic data


def build():
    raw = pd.read_csv(ROOT / "data" / "synthetic_orders_messy.csv", dtype=str, keep_default_na=False)
    frame = clean_orders(raw, rule_based_map(raw).mapping()).frame
    report = retention_report(frame, window_days=90, cost_to_win=COST_TO_WIN)
    obs = sc.observed_inputs(frame, 12, None)
    inputs = sc.Inputs(budget=10000, acquisition_share=0.8, cost_to_win=60, cost_to_bring_back=25, value_new=obs["value_new"],
                       extra_orders=obs["extra_orders"], order_value=obs["order_value"])
    sim = sc.simulate(inputs, sc.ranges_from_pct(inputs, 0.25))
    best = round(sim.best_median * 100)
    scenario = ins.scenario_facts(inputs, sim, best, 12, obs["basis"])
    facts = ins.build_facts(report, monthly_orders(frame), 90, COST_TO_WIN, scenario)
    return frame, report, facts


def main() -> None:
    send = "--send" in sys.argv
    frame, report, facts = build()
    prompts = {
        "1. AI summary": ins.summary_prompt(facts),
        "2. Segment ideas": ins.ideas_prompt(ins.segment_facts(report)),
        "3. Ask your data": askdata.sql_prompt(QUESTION, frame),
    }
    if not send:
        for name, prompt in prompts.items():
            print("=" * 78 + f"\n{name}  ({len(prompt):,} characters)\n" + "=" * 78 + "\n" + prompt + "\n")
        print("DRY RUN. Nothing was sent. Add --send to make three calls.")
        return

    text_fn, json_fn = gemini_ai_function(json_mode=False), gemini_ai_function(json_mode=True)
    if text_fn is None or json_fn is None:
        sys.exit("No usable GEMINI_API_KEY and GEMINI_MODEL found in .env.")
    budget = ins.CallBudget(limit=3)
    text_fn, json_fn = ins.with_budget(text_fn, budget), ins.with_budget(json_fn, budget)

    summary = ins.generate_summary(facts, text_fn)
    print("1. SUMMARY\nsource:", summary.source, "\nnote:", summary.note, "\n" + summary.text + "\n")
    if summary.source == "ai":
        print("checker:", check_text(summary.text, facts, max_words=ins.SUMMARY_MAX_WORDS).ok, "\n")

    ideas = ins.generate_ideas(ins.segment_facts(report), json_fn)
    print("2. SEGMENT IDEAS\nnote:", ideas.note)
    for name, items in ideas.ideas.items():
        print(f"  {name} [{ideas.source[name]}]:", " | ".join(items))

    print("\n3. ASK YOUR DATA\nquestion:", QUESTION)
    try:
        answer = askdata.ask(frame, QUESTION, json_fn)
        print("title:", answer.title, "\nsql:", answer.result.sql, "\nrows returned:", len(answer.result.table))
        print(answer.result.table.head(5).to_string(index=False))
    except askdata.AskError as err:
        print("refused or failed:", err)
    print(f"\nmodel calls made: {budget.used}")


if __name__ == "__main__":
    main()
