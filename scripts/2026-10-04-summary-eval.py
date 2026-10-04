"""How often does the AI summary pass the checker on the first try?

Runs the summary on five different synthetic datasets, one call each with retries off, and reports
how many passed and why the others failed. By default this is a dry run that prints the first prompt
and contacts nobody. Add --send to make the five calls. The key is read from .env and never printed.
    python scripts/2026-10-04-summary-eval.py
    python scripts/2026-10-04-summary-eval.py --send
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src import insights as ins  # noqa: E402
from src import scenario as sc  # noqa: E402
from src.checker import check_text  # noqa: E402
from src.cleaning import clean_orders  # noqa: E402
from src.mapper import gemini_ai_function, rule_based_map  # noqa: E402
from src.metrics import monthly_orders, retention_report  # noqa: E402
from src.sample_data import generate_orders  # noqa: E402

# seed, customers, cost to win, margin percent, shift percent for the scenario or None
VARIANTS = [
    (42, 1500, 60.0, None, 50), (7, 700, None, None, None), (11, 500, 40.0, 40.0, None),
    (5, 900, 75.0, None, 10), (23, 1100, 55.0, 30.0, 25),
]


def facts_for(seed: int, customers: int, cost, margin, shift):
    raw, _ = generate_orders(seed=seed, n_customers=customers)
    raw = raw.astype(str)
    frame = clean_orders(raw, rule_based_map(raw).mapping()).frame
    report = retention_report(frame, window_days=90, cost_to_win=cost, margin_pct=margin)
    scenario = None
    if shift is not None:
        obs = sc.observed_inputs(frame, 12, margin)
        inputs = sc.Inputs(budget=10000, acquisition_share=0.8, cost_to_win=cost or 60.0, cost_to_bring_back=25,
                           value_new=obs["value_new"], extra_orders=obs["extra_orders"], order_value=obs["order_value"])
        sim = sc.simulate(inputs, sc.ranges_from_pct(inputs, 0.25))
        low, high = sc.allowed_shift_pct(0.8)
        scenario = ins.scenario_facts(inputs, sim, max(low, min(high, shift)), 12, obs["basis"])
    return ins.build_facts(report, monthly_orders(frame), 90, cost, scenario)


def main() -> None:
    send = "--send" in sys.argv
    all_facts = [facts_for(*v) for v in VARIANTS]
    if not send:
        print(ins.summary_prompt(all_facts[0]))
        print("\nDRY RUN. Nothing was sent. Add --send to make five calls.")
        return
    text_fn = gemini_ai_function(json_mode=False)
    if text_fn is None:
        sys.exit("No usable GEMINI_API_KEY and GEMINI_MODEL found in .env.")
    budget = ins.CallBudget(limit=len(VARIANTS))
    ai = ins.with_budget(text_fn, budget)
    passed = 0
    for i, (variant, facts) in enumerate(zip(VARIANTS, all_facts), start=1):
        result = ins.generate_summary(facts, ai, retries=0)
        ok = result.source == "ai"
        passed += ok
        print(f"--- {i}. seed {variant[0]}: {'PASSED the check' if ok else 'DISCARDED'}")
        if ok:
            print(result.text)
        else:
            print(result.note)
    print(f"\nfirst-try pass rate: {passed} of {len(VARIANTS)}. model calls made: {budget.used}")


if __name__ == "__main__":
    main()
