"""One live column-matching call to Gemini on the synthetic sample.

Reads GEMINI_API_KEY and GEMINI_MODEL from .env without printing the key.
Makes exactly one model call. Run from the project folder:
    python scripts/2026-10-03-live-gemini-check.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.mapper import FIELDS, gemini_ai_function, map_columns, rule_based_map  # noqa: E402


def load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip())


def redact(text: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    return text.replace(key, "<key>") if key else text


def main() -> None:
    load_env(ROOT / ".env")
    ai_fn = gemini_ai_function()
    if ai_fn is None:
        sys.exit("No usable GEMINI_API_KEY and GEMINI_MODEL found in .env.")
    print("model:", os.environ["GEMINI_MODEL"])

    seen: dict = {"calls": 0}

    def recorded(prompt: str) -> str:
        seen["calls"] += 1
        seen["prompt_chars"] = len(prompt)
        try:
            reply = ai_fn(prompt)
        except Exception as err:
            seen["error"] = f"{type(err).__name__}: {redact(str(err))[:600]}"
            raise
        seen["reply"] = reply
        return reply

    raw = pd.read_csv(ROOT / "data" / "synthetic_orders_messy.csv", dtype=str, keep_default_na=False)
    rules = rule_based_map(raw)
    result = map_columns(raw, ai_fn=recorded)

    print("model calls made:", seen["calls"], "| prompt characters:", seen.get("prompt_chars"))
    if "error" in seen:
        print("CALL FAILED:", seen["error"])
    else:
        print("raw model reply:\n" + str(seen.get("reply")))
    print("AI reply accepted by the strict parser:", result.ai_used)
    print()
    print(f"{'field':14} {'rules':20} {'merged':20} {'confidence':10} source")
    for f in FIELDS:
        m = result.matches[f]
        print(f"{f:14} {str(rules.matches[f].header):20} {str(m.header):20} {m.confidence:10} {m.source}")
    for w in result.warnings:
        print("warning:", w)


if __name__ == "__main__":
    main()
