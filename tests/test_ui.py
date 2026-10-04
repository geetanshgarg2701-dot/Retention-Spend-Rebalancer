import re

import pytest

from src import ui
from src.ui import PALETTE, PILL_TEXT, TINT_STEPS, funnel_html, hero_html, pill_html, points_html, stepper_html, tint_style


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ------------------------------------------------------------------- contrast

@pytest.mark.parametrize("fg, bg", [
    ("text", "page"), ("text", "panel"), ("muted", "page"), ("muted", "panel"), ("muted", "track"),
    ("teal", "page"), ("teal", "panel"), ("on_teal", "teal"),
    ("amber", "panel"), ("clay", "panel"), ("text", "track"),
])
def test_text_pairs_meet_four_and_a_half_to_one(fg, bg):
    assert contrast(PALETTE[fg], PALETTE[bg]) >= 4.5


@pytest.mark.parametrize("upper, fill, ink", TINT_STEPS)
def test_cohort_tints_are_readable(upper, fill, ink):
    assert contrast(ink, fill) >= 4.5


def test_input_border_meets_three_to_one():
    config = open(".streamlit/config.toml", encoding="utf-8").read()
    border = re.search(r'borderColor\s*=\s*"(#[0-9A-Fa-f]{6})"', config).group(1)
    assert contrast(border, PALETTE["page"]) >= 3.0


# ----------------------------------------------------------- design rules

def test_css_follows_the_design_rules():
    css = ui.CSS.lower()
    assert "gradient" not in css
    assert "box-shadow" not in css and "drop-shadow" not in css and "text-shadow" not in css
    assert "text-transform" not in css  # no all-caps labels
    assert "#fff;" not in css and "#ffffff" not in css
    assert not re.search(r"(?<![-\w])white(?![-\w])", css)  # no pure white, white-space is fine
    assert "#000;" not in css and "#000000" not in css
    assert not re.search(r"(?<![-\w])black(?![-\w])", css)
    for banned in ("inter", "geist", "space grotesk"):
        assert not re.search(rf"font-family:[^;]*\b{banned}\b", css)
    assert "<script" not in css


def test_css_has_phone_rules_for_title_and_funnel():
    assert "@media (max-width: 40rem)" in ui.CSS
    assert "h1 {" in ui.CSS and ".rsr-frow { grid-template-columns: 1fr" in ui.CSS


def test_palette_has_no_pure_white_or_black_and_no_purple():
    for value in PALETTE.values():
        assert value.upper() not in {"#FFFFFF", "#000000"}
        r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        assert not (b > r + 20 and b > g + 20 and r > g)  # blue-violet hues


# ------------------------------------------------------------------ the helpers

def test_stepper_marks_done_current_and_upcoming():
    out = stepper_html(3)
    assert out.count("is-done") == 2 and out.count("is-current") == 1
    assert out.count("<li") == 4 and 'aria-current="step"' in out
    for name in ui.STEPS:
        assert name in out
    assert "rsr-step is-current" in out and out.index("Review cleaning") > out.index("is-current")


def test_stepper_at_the_first_stage_has_nothing_done():
    assert stepper_html(1).count("is-done") == 0


@pytest.mark.parametrize("level", ["high", "medium", "low", "none"])
def test_pills_say_the_level_in_words(level):
    out = pill_html(level)
    assert PILL_TEXT[level] in out and f'class="rsr-pill {level}"' in out


def test_unknown_pill_level_falls_back_to_not_matched():
    assert "Not matched" in pill_html("surprise")


HOSTILE = '<script>alert(1)</script><img src=x onerror=alert(2)> "quoted" & more'


def test_every_helper_escapes_user_text():
    outputs = [
        hero_html(HOSTILE),
        points_html([(HOSTILE, HOSTILE)]),
        funnel_html([(HOSTILE, 5, 0.5, 0.5)]),
    ]
    for out in outputs:
        assert "<script" not in out and "<img" not in out
        assert "&lt;script&gt;" in out


def test_funnel_rows_show_counts_and_clamp_widths():
    out = funnel_html([("Ordered once", 1378, 1.0, None), ("Ordered twice", 460, 0.334, 0.334), ("Odd", 1, 2.5, 0.0)])
    assert "1,378" in out and "33%" in out and "of the step before" in out
    assert "width:100.0%" in out and "width:33.4%" in out
    assert out.count("width:100.0%") == 2  # the 2.5 share is clamped
    assert out.count("of the step before") == 2  # the first row has nothing before it


def test_tint_style_steps_and_blanks():
    assert tint_style(float("nan")) == ""
    assert tint_style(0.02) != tint_style(0.15) != tint_style(0.9)
    assert tint_style(1.0).startswith("background-color: #8EDCE3")
