import re

import pytest

from src import ui
from src.ui import (
    FUNNEL_LAYERS,
    PALETTE,
    PILL_TEXT,
    TINT_STEPS,
    card_html,
    funnel_html,
    hero_html,
    pill_html,
    points_html,
    progress_html,
    segment_strip_html,
    stepper_html,
    tint_style,
)


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


HOSTILE = '<script>alert(1)</script><img src=x onerror=alert(2)> "quoted" & more'


# ------------------------------------------------------------------- contrast

@pytest.mark.parametrize("fg, bg", [
    ("text", "page"), ("text", "panel"), ("muted", "page"), ("muted", "panel"), ("muted", "track"),
    ("teal", "page"), ("teal", "panel"), ("teal", "track"), ("on_teal", "teal"),
    ("amber", "panel"), ("clay", "panel"), ("text", "track"),
])
def test_text_pairs_meet_four_and_a_half_to_one(fg, bg):
    assert contrast(PALETTE[fg], PALETTE[bg]) >= 4.5


@pytest.mark.parametrize("upper, fill, ink", TINT_STEPS)
def test_cohort_tints_are_readable(upper, fill, ink):
    assert contrast(ink, fill) >= 4.5


@pytest.mark.parametrize("fill, ink", FUNNEL_LAYERS)
def test_funnel_layers_are_readable(fill, ink):
    assert contrast(ink, fill) >= 4.5


def test_input_border_meets_three_to_one():
    config = open(".streamlit/config.toml", encoding="utf-8").read()
    border = re.search(r'borderColor\s*=\s*"(#[0-9A-Fa-f]{6})"', config).group(1)
    assert contrast(border, PALETTE["page"]) >= 3.0
    assert border.upper() == PALETTE["edge"].upper()


def test_hexagon_outlines_and_segment_fills_are_visible_against_the_page():
    assert contrast(PALETTE["edge"], PALETTE["page"]) >= 3.0
    for color in ui.SEGMENT_COLORS.values():
        assert contrast(color, PALETTE["panel"]) >= 3.0


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
    assert "<script" not in css and "javascript" not in css


def test_motion_is_subtle_and_respects_reduced_motion():
    css = ui.CSS
    assert "@media (prefers-reduced-motion: reduce)" in css
    reduced = css[css.index("prefers-reduced-motion"):]
    assert "animation: none !important" in reduced
    for duration in re.findall(r"animation:[^;]*?(\d+)ms", css):
        assert int(duration) <= 900  # nothing slow or looping
    assert "infinite" not in css


def test_css_has_phone_rules():
    assert "@media (max-width: 40rem)" in ui.CSS
    assert "h1 {" in ui.CSS and ".rsr-funnel { grid-template-columns: 1fr" in ui.CSS
    assert ".rsr-cluster { display: none" in ui.CSS


def test_palette_has_no_pure_white_or_black_and_no_purple():
    for value in PALETTE.values():
        assert value.upper() not in {"#FFFFFF", "#000000"}
        r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        assert not (b > r + 20 and b > g + 20 and r > g)  # blue-violet hues


# ------------------------------------------------------------------ the stepper

def test_stepper_marks_done_current_and_upcoming_with_hexagons():
    out = stepper_html(3)
    assert out.count("is-done") == 2 and out.count("is-current") == 1
    assert out.count("<li") == 4 and 'aria-current="step"' in out
    assert out.count('class="rsr-hex"') == 4
    for name in ui.STEPS:
        assert name in out
    assert out.index("Review cleaning") > out.index("is-current")


def test_stepper_at_the_first_stage_has_nothing_done():
    assert stepper_html(1).count("is-done") == 0


def test_hexagon_uses_a_flat_clip_path():
    assert "clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%)" in ui.CSS


# ------------------------------------------------------------------- pills

@pytest.mark.parametrize("level", ["high", "medium", "low", "none"])
def test_pills_say_the_level_in_words(level):
    out = pill_html(level)
    assert PILL_TEXT[level] in out and f'class="rsr-pill {level}"' in out


def test_unknown_pill_level_falls_back_to_not_matched():
    assert "Not matched" in pill_html("surprise")


# ----------------------------------------------------------------------- hero

def test_hero_sets_the_last_headline_word_in_emphasis_and_lists_tags_and_nodes():
    out = hero_html("A label", "Keep the customers you paid for", "Lead text.", ["One", "Two"], ["Load", "Match", "Clean", "Measure"])
    assert '<em>for</em>' in out and "Keep the customers you paid" in out
    assert out.count('class="rsr-tag"') == 2 and out.count('class="rsr-node"') == 4
    assert 'aria-hidden="true"' in out  # the decorative cluster is hidden from screen readers


# ---------------------------------------------------------- command cards

def test_the_ui_module_does_not_rely_on_inline_svg():
    # Streamlit's HTML sanitizer strips inline SVG, so charts use Streamlit's own elements instead.
    assert not hasattr(ui, "sparkline_html")
    assert "<svg" not in ui.CSS


def test_segment_strip_names_every_segment_and_skips_empty_ones():
    out = segment_strip_html([("Champions", 3), ("Loyal", 1), ("Lapsed", 0)])
    assert "Champions 3" in out and "Loyal 1" in out and "Lapsed" not in out
    assert "width:75.00%" in out and "width:25.00%" in out


@pytest.mark.parametrize("share, expected", [(0.5, "50.0%"), (2.0, "100.0%"), (-1.0, "0.0%")])
def test_progress_bar_clamps(share, expected):
    assert f"width:{expected}" in progress_html(share, "Payback progress")


def test_card_body_escapes_text_and_keeps_the_visual():
    out = card_html(HOSTILE, HOSTILE, HOSTILE, progress_html(0.5, "x"))
    assert "<script" not in out and "<img" not in out and "&lt;script&gt;" in out
    assert out.startswith('<div class="rsr-cardbody">') and "rsr-card-value" in out and "rsr-progress" in out


def test_every_helper_escapes_user_text():
    for out in (
        hero_html(HOSTILE, HOSTILE, HOSTILE, [HOSTILE], [HOSTILE]),
        points_html([(HOSTILE, HOSTILE)]),
        funnel_html([(HOSTILE, 5, 0.5, 0.5)]),
        segment_strip_html([(HOSTILE, 3)]),
        progress_html(0.5, HOSTILE),
    ):
        assert "<script" not in out and "<img" not in out  # no raw tags
        assert '"quoted"' not in out  # quotes are escaped, so no attribute can be broken out of
        assert "&lt;script&gt;" in out


# --------------------------------------------------------------------- funnel

def test_funnel_has_one_layer_and_one_legend_item_per_row():
    rows = [("At least 1 order", 1378, 1.0, None), ("2 or more orders", 460, 0.334, 0.334), ("3 or more orders", 165, 0.12, 0.36)]
    out = funnel_html(rows)
    assert out.count('class="rsr-flayer"') == 3 and out.count('class="rsr-fitem"') == 3
    assert "1,378" in out and "460" in out and "33% of customers" in out and "33% of the step before" in out
    assert out.count("of the step before") == 2  # the first row has nothing before it


def test_funnel_layer_widths_follow_the_square_root_of_the_share():
    out = funnel_html([("a", 100, 1.0, None), ("b", 25, 0.25, 0.25), ("c", 1, 0.01, 0.04)])
    widths = [float(w) for w in re.findall(r"width:([\d.]+)%;background", out)]
    assert widths == [100.0, 50.0, 20.0]  # sqrt 1, sqrt 0.25, and sqrt 0.01 raised to the 20 percent floor
    assert widths == sorted(widths, reverse=True)


def test_funnel_layers_taper_toward_the_next_layer():
    out = funnel_html([("a", 100, 1.0, None), ("b", 25, 0.25, 0.25), ("c", 1, 0.01, 0.04)])
    insets = [float(i) for i in re.findall(r"clip-path:polygon\(0 0,100% 0,[\d.]+% 100%,([\d.]+)% 100%\)", out)]
    assert insets[0] == pytest.approx(25.0)  # (100 - 50) / 2 / 100
    assert insets[1] == pytest.approx(30.0)  # (50 - 20) / 2 / 50
    assert insets[2] == pytest.approx(10.0)  # the last layer narrows by a fifth of its own width


def test_funnel_clamps_odd_shares():
    out = funnel_html([("a", 1, 2.5, None), ("b", 0, -1.0, 0.0)])
    assert "width:100.0%" in out and "width:20.0%" in out


# ---------------------------------------------------------------------- tints

def test_tint_style_steps_and_blanks():
    assert tint_style(float("nan")) == ""
    assert tint_style(0.02) != tint_style(0.15) != tint_style(0.9)
    assert tint_style(1.0).startswith("background-color: #8EDCE3")
