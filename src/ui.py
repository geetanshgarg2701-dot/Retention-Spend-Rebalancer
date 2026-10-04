"""Presentation helpers for the app.

All HTML here is static, or built from strings that are escaped first, because
file names, headers and values come from the user. No scripts are used.
"""
from __future__ import annotations

import html
from typing import Iterable, Optional

import streamlit as st

# Keep in step with .streamlit/config.toml. tests/test_ui.py checks contrast for these.
PALETTE = {
    "page": "#12191C",
    "panel": "#1A2428",
    "track": "#222F34",
    "line": "#2B383D",
    "text": "#E8EEEC",
    "muted": "#9FB0B3",
    "teal": "#3BB5C0",
    "on_teal": "#0E1417",
    "amber": "#E0B15B",
    "clay": "#E58B7B",
}

# Cohort retention tints, five discrete steps, as solid fills. Not a gradient.
TINT_STEPS = [
    (0.05, "#1D2E33", "#E8EEEC"),
    (0.10, "#21424A", "#E8EEEC"),
    (0.20, "#25636D", "#E8EEEC"),
    (0.40, "#3BB5C0", "#0E1417"),
    (1.01, "#8EDCE3", "#0E1417"),
]

STEPS = ["Load orders", "Confirm columns", "Review cleaning", "Retention results"]

PILL_TEXT = {
    "high": "High confidence",
    "medium": "Medium confidence",
    "low": "Low confidence, check this",
    "none": "Not matched",
}

_P = PALETTE
CSS = f"""
<style>
.rsr-stepper {{ display: flex; flex-wrap: wrap; gap: 0.5rem 0.75rem; margin: 0.25rem 0 1.5rem 0; padding: 0; list-style: none; }}
.rsr-step {{ display: flex; align-items: center; gap: 0.55rem; padding: 0.4rem 0.9rem 0.4rem 0.45rem;
  border: 1px solid {_P['line']}; border-radius: 999px; color: {_P['muted']}; font-size: 0.92rem; background: transparent; }}
.rsr-step .rsr-num {{ display: inline-flex; align-items: center; justify-content: center; width: 1.6rem; height: 1.6rem;
  border-radius: 999px; border: 1px solid {_P['muted']}; font-size: 0.82rem; font-variant-numeric: tabular-nums; }}
.rsr-step.is-done {{ color: {_P['text']}; }}
.rsr-step.is-done .rsr-num {{ background: {_P['track']}; border-color: {_P['teal']}; color: {_P['teal']}; }}
.rsr-step.is-current {{ color: {_P['on_teal']}; background: {_P['teal']}; border-color: {_P['teal']}; font-weight: 600; }}
.rsr-step.is-current .rsr-num {{ border-color: {_P['on_teal']}; color: {_P['on_teal']}; }}

.rsr-hero {{ padding: 0.5rem 0 1rem 0; max-width: 46rem; }}
.rsr-hero p {{ color: {_P['muted']}; font-size: 1.12rem; line-height: 1.55; margin: 0; }}

.rsr-points {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 0.9rem; margin: 0.5rem 0 1.25rem 0; }}
.rsr-point {{ background: {_P['panel']}; border: 1px solid {_P['line']}; border-radius: 0.9rem; padding: 1rem 1.1rem; }}
.rsr-point strong {{ display: block; color: {_P['text']}; font-size: 1.05rem; margin-bottom: 0.3rem; }}
.rsr-point span {{ color: {_P['muted']}; font-size: 0.95rem; line-height: 1.5; }}

.rsr-pill {{ display: inline-block; padding: 0.15rem 0.7rem; border-radius: 999px; font-size: 0.85rem; border: 1px solid; white-space: nowrap; }}
.rsr-pill.high {{ color: {_P['teal']}; border-color: {_P['teal']}; }}
.rsr-pill.medium {{ color: {_P['amber']}; border-color: {_P['amber']}; }}
.rsr-pill.low {{ color: {_P['clay']}; border-color: {_P['clay']}; }}
.rsr-pill.none {{ color: {_P['muted']}; border-color: {_P['muted']}; }}

.rsr-funnel {{ background: {_P['panel']}; border: 1px solid {_P['line']}; border-radius: 0.9rem; padding: 1rem 1.2rem; margin: 0.25rem 0 0.5rem 0; }}
.rsr-frow {{ display: grid; grid-template-columns: 9.5rem 1fr 11rem; align-items: center; gap: 0.9rem; padding: 0.35rem 0; }}
.rsr-flabel {{ color: {_P['text']}; font-size: 0.95rem; }}
.rsr-ftrack {{ background: {_P['track']}; border-radius: 0.5rem; height: 1.5rem; overflow: hidden; }}
.rsr-fbar {{ background: {_P['teal']}; height: 100%; border-radius: 0.5rem; min-width: 2px; }}
.rsr-fvalue {{ color: {_P['muted']}; font-size: 0.92rem; font-variant-numeric: tabular-nums; text-align: right; }}
.rsr-fvalue b {{ color: {_P['text']}; font-weight: 600; }}
@media (max-width: 40rem) {{
  .rsr-frow {{ grid-template-columns: 1fr; gap: 0.3rem; padding: 0.55rem 0; }}
  .rsr-fvalue {{ text-align: left; }}
}}

[data-testid="stMetricValue"] {{ font-family: "Fraunces", serif; font-weight: 600; }}
@media (max-width: 40rem) {{
  h1 {{ font-size: 2.1rem !important; line-height: 1.15 !important; }}
}}
</style>
"""


def inject_css() -> None:
    st.html(CSS)


def stepper_html(stage: int) -> str:
    items = []
    for number, name in enumerate(STEPS, start=1):
        state = "is-current" if number == stage else ("is-done" if number < stage else "")
        current = ' aria-current="step"' if number == stage else ""
        items.append(
            f'<li class="rsr-step {state}"{current}><span class="rsr-num">{number}</span>{html.escape(name)}</li>'
        )
    return f'<ol class="rsr-stepper" aria-label="Progress">{"".join(items)}</ol>'


def stepper(stage: int) -> None:
    st.html(stepper_html(stage))


def hero_html(lead: str) -> str:
    return f'<div class="rsr-hero"><p>{html.escape(lead)}</p></div>'


def points_html(points: Iterable[tuple[str, str]]) -> str:
    cards = "".join(
        f'<div class="rsr-point"><strong>{html.escape(title)}</strong><span>{html.escape(text)}</span></div>'
        for title, text in points
    )
    return f'<div class="rsr-points">{cards}</div>'


def pill_html(level: str) -> str:
    level = level if level in PILL_TEXT else "none"
    return f'<span class="rsr-pill {level}">{html.escape(PILL_TEXT[level])}</span>'


def funnel_html(rows: Iterable[tuple[str, int, float, Optional[float]]]) -> str:
    """Rows are label, customers, share of all customers, and share of the step before."""
    out = []
    for label, customers, share, of_previous in rows:
        width = max(0.0, min(1.0, share)) * 100
        detail = f"<b>{customers:,}</b> customers, {share:.0%}"
        if of_previous is not None:
            detail += f", {of_previous:.0%} of the step before"
        out.append(
            f'<div class="rsr-frow"><div class="rsr-flabel">{html.escape(label)}</div>'
            f'<div class="rsr-ftrack"><div class="rsr-fbar" style="width:{width:.1f}%"></div></div>'
            f'<div class="rsr-fvalue">{detail}</div></div>'
        )
    return f'<div class="rsr-funnel" role="group" aria-label="Customers by number of orders">{"".join(out)}</div>'


def tint_style(value: float) -> str:
    """Inline CSS for a cohort cell, or an empty string for a blank cell."""
    if value != value:  # NaN
        return ""
    for upper, fill, ink in TINT_STEPS:
        if value < upper:
            return f"background-color: {fill}; color: {ink}"
    return ""
