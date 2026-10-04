"""Presentation helpers for the app.

All HTML here is static, or built from strings that are escaped first, because
file names, headers and values come from the user. No scripts are used.
Colors are flat fills. There are no gradients, shadows or all-caps labels.
"""
from __future__ import annotations

import html
from typing import Iterable, Optional, Sequence

import streamlit as st

# Keep in step with .streamlit/config.toml. tests/test_ui.py checks contrast for these.
PALETTE = {
    "page": "#12191C",
    "panel": "#1A2428",
    "track": "#222F34",
    "line": "#2B383D",
    "edge": "#5E7279",
    "text": "#E8EEEC",
    "muted": "#9FB0B3",
    "teal": "#3BB5C0",
    "on_teal": "#0E1417",
    "amber": "#E0B15B",
    "clay": "#E58B7B",
    "sage": "#8FB8A8",
    "sky": "#6FA3D8",
}

# Cohort tints and funnel layers, five discrete solid steps, each with a readable ink color.
TINT_STEPS = [
    (0.05, "#1D2E33", "#E8EEEC"),
    (0.10, "#21424A", "#E8EEEC"),
    (0.20, "#25636D", "#E8EEEC"),
    (0.40, "#3BB5C0", "#0E1417"),
    (1.01, "#8EDCE3", "#0E1417"),
]
# Funnel layers from the widest to the narrowest, as fill and ink.
FUNNEL_FLOOR = 0.2
FUNNEL_LAYERS = [("#8EDCE3", "#0E1417"), ("#3BB5C0", "#0E1417"), ("#25636D", "#E8EEEC"), ("#21424A", "#E8EEEC")]

SEGMENT_COLORS = {
    "Champions": PALETTE["teal"], "Loyal": PALETTE["sage"], "New": PALETTE["sky"],
    "Occasional": PALETTE["muted"], "At risk": PALETTE["amber"], "Lapsed": PALETTE["clay"],
}

STEPS = ["Load orders", "Confirm columns", "Review cleaning", "Retention results", "Budget scenario"]

PILL_TEXT = {
    "high": "High confidence",
    "medium": "Medium confidence",
    "low": "Low confidence, check this",
    "none": "Not matched",
}

_P = PALETTE
_HEX = "polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%)"
CSS = f"""
<style>
@keyframes rsr-rise {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes rsr-grow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}

.rsr-stepper {{ display: flex; margin: 0.25rem 0 1.75rem 0; padding: 0; list-style: none; }}
.rsr-step {{ position: relative; display: flex; flex-direction: column; align-items: center; gap: 0.5rem; flex: 1 1 0;
  min-width: 0; color: {_P['muted']}; font-size: 0.9rem; text-align: center; }}
.rsr-step::before {{ content: ""; position: absolute; top: 1.65rem; left: -50%; width: 100%; height: 2px; background: {_P['line']}; }}
.rsr-step:first-child::before {{ display: none; }}
.rsr-step.is-done::before, .rsr-step.is-current::before {{ background: {_P['teal']}; }}
.rsr-hex {{ position: relative; z-index: 1; display: grid; place-items: center; width: 3rem; height: 3.3rem;
  background: {_P['edge']}; clip-path: {_HEX}; }}
.rsr-hex-in {{ display: grid; place-items: center; width: calc(100% - 4px); height: calc(100% - 4px);
  background: {_P['page']}; clip-path: {_HEX}; color: {_P['muted']}; font-weight: 600; font-variant-numeric: tabular-nums; }}
.rsr-step.is-done {{ color: {_P['text']}; }}
.rsr-step.is-done .rsr-hex {{ background: {_P['teal']}; }}
.rsr-step.is-done .rsr-hex-in {{ background: {_P['track']}; color: {_P['teal']}; }}
.rsr-step.is-current {{ color: {_P['text']}; font-weight: 600; }}
.rsr-step.is-current .rsr-hex {{ background: {_P['teal']}; }}
.rsr-step.is-current .rsr-hex-in {{ background: {_P['teal']}; color: {_P['on_teal']}; }}
.rsr-step-name {{ line-height: 1.25; padding: 0 0.25rem; }}

.rsr-herogrid {{ display: grid; grid-template-columns: 1.35fr 1fr; gap: 2rem; align-items: center; margin: 0.5rem 0 1.25rem 0; }}
.rsr-eyebrow {{ color: {_P['teal']}; font-size: 0.95rem; font-weight: 600; margin: 0 0 0.6rem 0; }}
.rsr-headline {{ font-family: "Fraunces", serif; font-weight: 600; font-size: clamp(2rem, 4.6vw, 3.5rem); line-height: 1.08;
  color: {_P['text']}; margin: 0 0 1rem 0; }}
.rsr-headline em {{ color: {_P['teal']}; font-style: italic; }}
.rsr-lead {{ color: {_P['muted']}; font-size: 1.1rem; line-height: 1.55; margin: 0 0 1.1rem 0; max-width: 40rem; }}
.rsr-tags, .rsr-stepper {{ padding-inline-start: 0 !important; margin-inline: 0 !important; }}
.rsr-tags {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-block: 0; padding: 0; list-style: none; }}
.rsr-tag {{ display: inline-flex; align-items: center; gap: 0.45rem; padding: 0.25rem 0.8rem; border: 1px solid {_P['line']};
  border-radius: 999px; color: {_P['muted']}; font-size: 0.88rem; background: {_P['panel']}; }}
.rsr-tag::before {{ content: ""; width: 0.45rem; height: 0.45rem; border-radius: 999px; background: {_P['teal']}; }}
.rsr-cluster {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.6rem 0.4rem; justify-items: center; padding: 0.5rem; }}
.rsr-cluster .rsr-node:nth-child(even) {{ transform: translateY(1.4rem); }}
.rsr-node {{ display: flex; flex-direction: column; align-items: center; gap: 0.4rem; color: {_P['text']}; font-size: 0.88rem; text-align: center; }}
.rsr-node .rsr-hex {{ width: 4.6rem; height: 5.1rem; }}
.rsr-node .rsr-hex-in {{ background: {_P['panel']}; color: {_P['teal']}; font-size: 1.2rem; }}
.rsr-node .rsr-hex {{ background: {_P['teal']}; }}

.rsr-points {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 0.9rem; margin: 0.5rem 0 1.25rem 0; }}
.rsr-point {{ background: {_P['panel']}; border: 1px solid {_P['line']}; border-radius: 0.9rem; padding: 1rem 1.1rem; }}
.rsr-point strong {{ display: block; color: {_P['text']}; font-size: 1.05rem; margin-bottom: 0.3rem; }}
.rsr-point span {{ color: {_P['muted']}; font-size: 0.95rem; line-height: 1.5; }}

.rsr-pill {{ display: inline-block; padding: 0.15rem 0.7rem; border-radius: 999px; font-size: 0.85rem; border: 1px solid; white-space: nowrap; }}
.rsr-pill.high {{ color: {_P['teal']}; border-color: {_P['teal']}; }}
.rsr-pill.medium {{ color: {_P['amber']}; border-color: {_P['amber']}; }}
.rsr-pill.low {{ color: {_P['clay']}; border-color: {_P['clay']}; }}
.rsr-pill.none {{ color: {_P['muted']}; border-color: {_P['muted']}; }}

.rsr-cardbody {{ display: flex; flex-direction: column; gap: 0.35rem; }}
.rsr-card-label {{ color: {_P['muted']}; font-size: 0.9rem; }}
.rsr-card-value {{ font-family: "Fraunces", serif; font-weight: 600; font-size: 1.9rem; line-height: 1.1; color: {_P['text']}; }}
.rsr-card-note {{ color: {_P['muted']}; font-size: 0.85rem; line-height: 1.4; }}
.rsr-strip {{ display: flex; height: 0.8rem; border-radius: 999px; overflow: hidden; background: {_P['track']}; margin-top: 0.4rem; }}
.rsr-strip span {{ display: block; height: 100%; }}
.rsr-legend {{ display: flex; flex-wrap: wrap; gap: 0.2rem 0.8rem; margin-top: 0.4rem; color: {_P['muted']}; font-size: 0.8rem; }}
.rsr-legend i {{ display: inline-block; width: 0.55rem; height: 0.55rem; border-radius: 2px; margin-right: 0.3rem; }}
.rsr-progress {{ height: 0.8rem; border-radius: 999px; background: {_P['track']}; overflow: hidden; margin-top: 0.5rem; }}
.rsr-progress-fill {{ height: 100%; background: {_P['teal']}; border-radius: 999px; transform-origin: left center; }}

.rsr-funnel {{ display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 1.5rem; align-items: center;
  background: {_P['panel']}; border: 1px solid {_P['line']}; border-radius: 0.9rem; padding: 1.2rem; margin: 0.25rem 0 0.5rem 0; }}
.rsr-flayers {{ display: flex; flex-direction: column; align-items: center; gap: 4px; }}
.rsr-flayer {{ display: flex; align-items: center; justify-content: center; height: 3.1rem; font-weight: 600; font-variant-numeric: tabular-nums; }}
.rsr-flegend {{ display: flex; flex-direction: column; gap: 0.85rem; }}
.rsr-fitem {{ color: {_P['muted']}; font-size: 0.92rem; line-height: 1.35; }}
.rsr-fitem b {{ display: block; color: {_P['text']}; font-weight: 600; font-size: 1rem; }}
@media (max-width: 40rem) {{
  .rsr-funnel {{ grid-template-columns: 1fr; gap: 1rem; }}
  .rsr-herogrid {{ grid-template-columns: 1fr; }}
  .rsr-cluster {{ display: none; }}
  .rsr-step {{ font-size: 0.78rem; }}
  .rsr-hex {{ width: 2.5rem; height: 2.75rem; }}
  .rsr-step::before {{ top: 1.38rem; }}
  h1 {{ font-size: 2.1rem !important; line-height: 1.15 !important; }}
}}

.rsr-hero, .rsr-herogrid > div, .rsr-point, .rsr-cardbody, .rsr-funnel {{ animation: rsr-rise 480ms ease-out both; }}
.rsr-point:nth-child(2) {{ animation-delay: 80ms; }}
.rsr-point:nth-child(3) {{ animation-delay: 160ms; }}
.rsr-flayer {{ animation: rsr-rise 520ms ease-out both; }}
.rsr-flayer:nth-child(2) {{ animation-delay: 90ms; }}
.rsr-flayer:nth-child(3) {{ animation-delay: 180ms; }}
.rsr-flayer:nth-child(4) {{ animation-delay: 270ms; }}
.rsr-progress-fill {{ animation: rsr-grow 700ms ease-out both; }}
@media (prefers-reduced-motion: reduce) {{
  .rsr-herogrid > div, .rsr-point, .rsr-cardbody, .rsr-funnel, .rsr-flayer, .rsr-progress-fill {{
    animation: none !important; }}
}}

[data-testid="stMetricValue"] {{ font-family: "Fraunces", serif; font-weight: 600; }}
</style>
"""


def inject_css() -> None:
    st.html(CSS)


# ------------------------------------------------------------------ stepper and hero

def _hex(content: str) -> str:
    return f'<span class="rsr-hex"><span class="rsr-hex-in">{content}</span></span>'


def stepper_html(stage: int) -> str:
    items = []
    for number, name in enumerate(STEPS, start=1):
        state = "is-current" if number == stage else ("is-done" if number < stage else "")
        current = ' aria-current="step"' if number == stage else ""
        items.append(
            f'<li class="rsr-step {state}"{current}>{_hex(str(number))}'
            f'<span class="rsr-step-name">{html.escape(name)}</span></li>'
        )
    return f'<ol class="rsr-stepper" aria-label="Progress">{"".join(items)}</ol>'


def stepper(stage: int) -> None:
    st.html(stepper_html(stage))


def hero_html(
    eyebrow: str, headline: str, lead: str, tags: Sequence[str], nodes: Sequence[str], emphasis_words: int = 2,
) -> str:
    """The first screen. headline is plain text, and its last words are set in italic teal."""
    words = headline.split()
    split = max(0, len(words) - emphasis_words)
    lead_words, last = " ".join(words[:split]), " ".join(words[split:])
    tag_items = "".join(f'<li class="rsr-tag">{html.escape(t)}</li>' for t in tags)
    cluster = "".join(
        f'<div class="rsr-node">{_hex(str(i))}<span>{html.escape(n)}</span></div>' for i, n in enumerate(nodes, start=1)
    )
    return (
        '<div class="rsr-herogrid"><div>'
        f'<p class="rsr-eyebrow">{html.escape(eyebrow)}</p>'
        f'<h2 class="rsr-headline">{html.escape(lead_words)} <em>{html.escape(last)}</em></h2>'
        f'<p class="rsr-lead">{html.escape(lead)}</p>'
        f'<ul class="rsr-tags">{tag_items}</ul></div>'
        f'<div class="rsr-cluster" aria-hidden="true">{cluster}</div></div>'
    )


def tags_html(tags: Iterable[str]) -> str:
    """A row of small flat tags, for labels such as Estimate."""
    items = "".join(f'<li class="rsr-tag">{html.escape(t)}</li>' for t in tags)
    return f'<ul class="rsr-tags">{items}</ul>'


def points_html(points: Iterable[tuple[str, str]]) -> str:
    cards = "".join(
        f'<div class="rsr-point"><strong>{html.escape(title)}</strong><span>{html.escape(text)}</span></div>'
        for title, text in points
    )
    return f'<div class="rsr-points">{cards}</div>'


def pill_html(level: str) -> str:
    level = level if level in PILL_TEXT else "none"
    return f'<span class="rsr-pill {level}">{html.escape(PILL_TEXT[level])}</span>'


# ------------------------------------------------------------------ command cards

def segment_strip_html(items: Sequence[tuple[str, int]]) -> str:
    """A flat stacked bar plus a legend. The legend names every segment, so color is never the only cue."""
    total = sum(n for _, n in items) or 1
    spans = "".join(
        f'<span style="width:{n / total * 100:.2f}%;background:{SEGMENT_COLORS.get(name, PALETTE["muted"])}" '
        f'title="{html.escape(name)}: {n:,}"></span>'
        for name, n in items if n > 0
    )
    legend = "".join(
        f'<span><i style="background:{SEGMENT_COLORS.get(name, PALETTE["muted"])}"></i>{html.escape(name)} {n:,}</span>'
        for name, n in items if n > 0
    )
    return f'<div class="rsr-strip" role="img" aria-label="Customers by segment">{spans}</div><div class="rsr-legend">{legend}</div>'


def progress_html(share: float, label: str) -> str:
    share = max(0.0, min(1.0, share))
    return (
        f'<div class="rsr-progress" role="progressbar" aria-label="{html.escape(label)}" aria-valuemin="0" '
        f'aria-valuemax="100" aria-valuenow="{share * 100:.0f}">'
        f'<div class="rsr-progress-fill" style="width:{share * 100:.1f}%"></div></div>'
    )


def card_html(label: str, value: str, note: str = "", visual: str = "") -> str:
    """The inside of a bordered card. visual must already be built by the helpers above."""
    return (
        f'<div class="rsr-cardbody"><div class="rsr-card-label">{html.escape(label)}</div>'
        f'<div class="rsr-card-value">{html.escape(value)}</div>{visual}'
        f'<div class="rsr-card-note">{html.escape(note)}</div></div>'
    )


# ------------------------------------------------------------------ funnel and tints

def funnel_html(rows: Sequence[tuple[str, int, float, Optional[float]]]) -> str:
    """A tapering funnel in flat layers, with a legend. Rows are label, customers, share of all, share of the step before.

    Layer widths follow the square root of each share, with a floor, so small steps stay visible.
    The legend carries the exact numbers.
    """
    rows = list(rows)
    shares = [max(0.0, min(1.0, r[2])) for r in rows]
    widths = [max(FUNNEL_FLOOR, s ** 0.5) for s in shares]
    layers, legend = [], []
    for i, ((label, customers, share, of_previous), width) in enumerate(zip(rows, widths)):
        nxt = widths[i + 1] if i + 1 < len(widths) else width * 0.8
        inset = max(0.0, (width - nxt) / 2 / width * 100)
        fill, ink = FUNNEL_LAYERS[min(i, len(FUNNEL_LAYERS) - 1)]
        layers.append(
            f'<div class="rsr-flayer" style="width:{width * 100:.1f}%;background:{fill};color:{ink};'
            f'clip-path:polygon(0 0,100% 0,{100 - inset:.1f}% 100%,{inset:.1f}% 100%)">{customers:,}</div>'
        )
        detail = f"{share:.0%} of customers"
        if of_previous is not None:
            detail += f", {of_previous:.0%} of the step before"
        legend.append(f'<div class="rsr-fitem"><b>{html.escape(label)}</b>{customers:,} customers, {detail}</div>')
    return (
        '<div class="rsr-funnel" role="group" aria-label="Customers by number of orders">'
        f'<div class="rsr-flayers">{"".join(layers)}</div><div class="rsr-flegend">{"".join(legend)}</div></div>'
    )


def tint_style(value: float) -> str:
    """Inline CSS for a cohort cell, or an empty string for a blank cell."""
    if value != value:  # NaN
        return ""
    for upper, fill, ink in TINT_STEPS:
        if value < upper:
            return f"background-color: {fill}; color: {ink}"
    return ""
