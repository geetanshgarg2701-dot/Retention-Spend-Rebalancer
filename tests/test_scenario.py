"""Hand-checked scenario model.

Round numbers: a budget of 1,000, 80 percent on winning customers today, 50 to win one,
20 to bring one back. A new customer is worth 100. A brought-back customer places 2 extra
orders worth 30 each, so is worth 60.

Today, with no diminishing returns: 800 buys 16 new customers worth 1,600, and 200 buys
10 brought-back customers worth 600. Total 2,200.
Moving 100 toward retention: 700 buys 14 new customers worth 1,400, and 300 buys 15
brought-back customers worth 900. Total 2,300, so a gain of 100.
"""
import math

import numpy as np
import pandas as pd
import pytest

from src import scenario as sc
from src.scenario import Inputs, Ranges

BASE = Inputs(budget=1000, acquisition_share=0.8, cost_to_win=50, cost_to_bring_back=20,
              value_new=100, extra_orders=2, order_value=30, exponent=1.0)


def half(**kw):
    return Inputs(**{**BASE.__dict__, "exponent": 0.5, **kw})


def point_ranges(inputs):
    return Ranges((inputs.cost_to_win,) * 2, (inputs.cost_to_bring_back,) * 2,
                  (inputs.extra_orders,) * 2, (inputs.exponent,) * 2)


# ---------------------------------------------------------------- the model

def test_baseline_matches_the_hand_count():
    e = sc.evaluate(BASE, 0.0)
    assert (e["acquisition_spend"], e["retention_spend"]) == (800, 200)
    assert e["new_customers"] == pytest.approx(16) and e["brought_back"] == pytest.approx(10)
    assert e["value_from_new"] == pytest.approx(1600) and e["value_from_brought_back"] == pytest.approx(600)
    assert e["total_value"] == pytest.approx(2200)


def test_a_ten_percent_shift_matches_the_hand_count():
    e = sc.evaluate(BASE, 0.10)
    assert (e["acquisition_spend"], e["retention_spend"]) == (700, 300)
    assert e["new_customers"] == pytest.approx(14) and e["brought_back"] == pytest.approx(15)
    assert e["total_value"] == pytest.approx(2300)
    assert sc.delta_value(BASE, 0.10) == pytest.approx(100)


def test_moving_money_back_toward_acquisition_loses_value_when_retention_is_worth_more_per_dollar():
    # Each dollar buys 2 value in acquisition spend... 100 / 50 = 2 per dollar, and 60 / 20 = 3 per dollar in retention.
    assert sc.delta_value(BASE, -0.10) == pytest.approx(-100)


def test_diminishing_returns_with_exponent_one_half():
    expected = 1600 * math.sqrt(700 / 800) + 600 * math.sqrt(300 / 200) - 2200
    assert sc.delta_value(half(), 0.10) == pytest.approx(expected)
    assert expected == pytest.approx(31.50987, abs=1e-4)


def test_best_shift_with_no_diminishing_returns_is_the_largest_allowed_move():
    # Each moved dollar nets 3 minus 2, so the gain is 1 per dollar and rises to the 50 percent cap.
    best = sc.best_shift(BASE)
    assert best["shift"] == pytest.approx(0.5) and best["delta"] == pytest.approx(500)


def test_best_shift_with_exponent_one_half_is_sixteen_percent():
    # Setting the slope to zero: 3200 / (800 - x) = 1800 / (200 + x), so x = 160 of 1,000.
    best = sc.best_shift(half())
    assert best["shift"] == pytest.approx(0.16)
    expected = 1600 * math.sqrt(640 / 800) + 600 * math.sqrt(360 / 200) - 2200
    assert best["delta"] == pytest.approx(expected)
    assert best["delta"] > sc.delta_value(half(), 0.15) and best["delta"] > sc.delta_value(half(), 0.17)


def test_best_shift_is_zero_when_retention_is_worth_less_per_dollar():
    weak = half(extra_orders=0.5)  # a brought-back customer is worth 15, so 0.75 per dollar against 2
    assert sc.best_shift(weak)["shift"] <= 0


def test_no_retention_spend_today_uses_a_reference_spend_of_ten_percent():
    all_acq = Inputs(budget=1000, acquisition_share=1.0, cost_to_win=50, cost_to_bring_back=20,
                     value_new=100, extra_orders=2, order_value=30, exponent=1.0)
    # Reference retention spend is 100, which buys 5 customers, so 100 of spend buys 5 and 0 buys none.
    assert sc.evaluate(all_acq, 0.0)["brought_back"] == pytest.approx(0)
    shifted = sc.evaluate(all_acq, 0.10)
    assert shifted["brought_back"] == pytest.approx(5) and shifted["new_customers"] == pytest.approx(18)
    assert sc.delta_value(all_acq, 0.10) == pytest.approx(2100 - 2000)


@pytest.mark.parametrize("share, expected", [(0.8, (-20, 50)), (0.5, (-25, 50)), (0.3, (-25, 30)), (1.0, (0, 50)), (0.0, (-25, 0))])
def test_allowed_shift_range(share, expected):
    assert sc.allowed_shift_pct(share) == expected


def test_a_shift_that_empties_a_channel_is_refused():
    with pytest.raises(ValueError, match="below zero"):
        sc.evaluate(BASE, 0.9)


@pytest.mark.parametrize("change, message", [
    ({"budget": 0}, "budget"), ({"acquisition_share": 1.5}, "acquisition share"),
    ({"cost_to_win": 0}, "cost to win"), ({"cost_to_bring_back": -1}, "cost to win"),
    ({"extra_orders": -1}, "cannot be negative"), ({"exponent": 1.2}, "exponent"), ({"exponent": 0.05}, "exponent"),
])
def test_bad_inputs_get_plain_errors(change, message):
    with pytest.raises(ValueError, match=message):
        sc.validate(Inputs(**{**BASE.__dict__, **change}))


# ---------------------------------------------------------------- ranges

def test_ranges_from_a_percent_stay_in_bounds():
    r = sc.ranges_from_pct(half(), 0.25)
    assert r.cost_to_win == pytest.approx((37.5, 62.5)) and r.extra_orders == pytest.approx((1.5, 2.5))
    assert r.exponent == pytest.approx((0.375, 0.625))
    edge = sc.ranges_from_pct(Inputs(**{**BASE.__dict__, "exponent": 0.95}), 0.25)
    assert edge.exponent[1] == 1.0  # clipped to the largest allowed exponent
    low = sc.ranges_from_pct(Inputs(**{**BASE.__dict__, "exponent": 0.1}), 0.5)
    assert low.exponent[0] == 0.1


def test_range_checks():
    with pytest.raises(ValueError, match="include the value you entered"):
        sc.check_ranges(BASE, Ranges((60, 70), BASE_RANGE.cost_to_bring_back, BASE_RANGE.extra_orders, BASE_RANGE.exponent))
    with pytest.raises(ValueError, match="uncertainty"):
        sc.ranges_from_pct(BASE, 1.0)
    with pytest.raises(ValueError, match="above zero"):
        sc.check_ranges(BASE, Ranges((0, 60), BASE_RANGE.cost_to_bring_back, BASE_RANGE.extra_orders, BASE_RANGE.exponent))


BASE_RANGE = sc.ranges_from_pct(BASE, 0.25)


# ------------------------------------------------------------- simulation

def test_simulation_is_repeatable_and_the_seed_matters():
    a = sc.simulate(half(), draws=500, seed=1)
    b = sc.simulate(half(), draws=500, seed=1)
    c = sc.simulate(half(), draws=500, seed=2)
    np.testing.assert_array_equal(a.median, b.median)
    np.testing.assert_array_equal(a.p10, b.p10)
    assert not np.array_equal(a.median, c.median)


def test_simulation_covers_every_allowed_shift_and_includes_no_change():
    sim = sc.simulate(half(), draws=300)
    assert sim.shifts[0] == -0.20 and sim.shifts[-1] == 0.50 and 0.0 in sim.shifts
    assert len(sim.shifts) == 71 and len(sim.median) == 71


def test_no_change_has_no_gain_and_bands_are_ordered():
    sim = sc.simulate(half(), draws=500)
    zero = int(np.where(sim.shifts == 0)[0][0])
    assert sim.p10[zero] == sim.median[zero] == sim.p90[zero] == 0 and sim.prob_positive[zero] == 0
    assert np.all(sim.p10 <= sim.median + 1e-9) and np.all(sim.median <= sim.p90 + 1e-9)
    assert np.all((sim.prob_positive >= 0) & (sim.prob_positive <= 1))


def test_ranges_that_collapse_to_a_point_reproduce_the_exact_model():
    inputs = half()
    sim = sc.simulate(inputs, point_ranges(inputs), draws=50)
    for pct in (-20, -5, 10, 16, 50):
        i = int(np.where(np.round(sim.shifts * 100).astype(int) == pct)[0][0])
        want = sc.delta_value(inputs, pct / 100)
        assert sim.median[i] == pytest.approx(want) and sim.p10[i] == pytest.approx(want) and sim.p90[i] == pytest.approx(want)
        assert sim.prob_positive[i] == (1.0 if want > 0 else 0.0)
    assert sim.best_median == sim.best_p10 == sim.best_p90 == pytest.approx(0.16)
    assert sim.share_best_is_move == 1.0


def test_tiny_uncertainty_stays_close_to_the_exact_model():
    inputs = half()
    sim = sc.simulate(inputs, sc.ranges_from_pct(inputs, 0.001), draws=1000)
    i = int(np.where(np.round(sim.shifts * 100).astype(int) == 10)[0][0])
    assert sim.median[i] == pytest.approx(sc.delta_value(inputs, 0.10), rel=0.02)


def test_wider_uncertainty_widens_the_band():
    inputs = half()
    narrow = sc.simulate(inputs, sc.ranges_from_pct(inputs, 0.05), draws=800)
    wide = sc.simulate(inputs, sc.ranges_from_pct(inputs, 0.4), draws=800)
    i = int(np.where(np.round(narrow.shifts * 100).astype(int) == 20)[0][0])
    assert (wide.p90[i] - wide.p10[i]) > (narrow.p90[i] - narrow.p10[i])


# ------------------------------------------------------ observed from orders

ROWS = [
    ("A", "2024-01-10", 100), ("A", "2024-02-20", 50), ("A", "2024-04-05", 50),
    ("B", "2024-01-25", 40), ("B", "2024-01-30", 60),
    ("C", "2024-02-05", 80),
    ("D", "2024-02-15", 30), ("D", "2024-05-20", 70),
    ("E", "2024-05-10", 90), ("E", "2024-06-15", 10),
]


@pytest.fixture
def frame():
    df = pd.DataFrame(ROWS, columns=["customer_id", "order_date", "order_value"])
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def test_observed_inputs_match_the_hand_count(frame):
    o = sc.observed_inputs(frame, horizon_months=3)
    # Cumulative revenue per customer by month is 80, 92, 90, 120, 120, 150, so month index 2 is 90.
    assert o["value_new"] == pytest.approx(90.0) and o["value_new_month"] == 2 and o["history_short"] is False
    # Repeat customers A, B, D, E placed 2, 1, 1, 1 extra orders, so 5 over 4.
    assert o["extra_orders"] == pytest.approx(1.25) and o["repeat_customers"] == 4
    assert o["order_value"] == pytest.approx(58.0) and o["basis"] == "revenue"


def test_observed_inputs_fall_back_when_history_is_shorter_than_the_horizon(frame):
    o = sc.observed_inputs(frame, horizon_months=12)
    assert o["history_short"] is True and o["value_new_month"] == 5 and o["value_new"] == pytest.approx(150.0)


def test_observed_inputs_use_margin_when_given(frame):
    o = sc.observed_inputs(frame, horizon_months=3, margin_pct=50)
    assert o["value_new"] == pytest.approx(45.0) and o["order_value"] == pytest.approx(29.0) and o["basis"] == "margin"


def test_observed_inputs_with_no_repeat_customers(frame):
    once = frame.drop_duplicates("customer_id")
    assert sc.observed_inputs(once, 3)["extra_orders"] == 0.0
    with pytest.raises(ValueError, match="at least one month"):
        sc.observed_inputs(frame, 0)


# --------------------------------------------------------------- the words

def exact_sim(inputs, draws=500):
    return sc.simulate(inputs, point_ranges(inputs), draws=draws)


def test_summary_for_a_gain_names_the_move_the_range_and_says_estimate():
    text = sc.summarize(half(), exact_sim(half()), 10, 12, "revenue")
    assert "moving 10% of the budget to retention is estimated to add about 32 in revenue over 12 months" in text
    assert "range of 32 to 32" in text and "100% of 500 simulations" in text
    assert "about 16% of the budget toward retention" in text
    assert "estimates that depend on your assumptions" in text and "not a forecast" in text


def test_summary_for_a_move_back_to_acquisition_and_for_a_loss():
    back = sc.summarize(half(), exact_sim(half()), -10, 12, "revenue")
    assert "to winning new customers" in back and "to lose about" in back or "lose about" in back
    assert "-" in back  # the loss shows with a minus sign in the range


def test_summary_for_no_change_and_for_keeping_the_split():
    # Acquisition is worth 100 / 50 = 2 per dollar. Retention is worth (4/3 * 30) / 20 = 2 per dollar.
    # With equal value per dollar and diminishing returns, today's split is already the best.
    balanced = half(extra_orders=4 / 3)
    sim = exact_sim(balanced)
    assert sc.best_shift(balanced)["shift"] == 0
    text = sc.summarize(balanced, sim, 0, 12, "margin")
    assert text.startswith("Keeping today's split is the baseline")
    assert "Keeping today's split was the best choice in most simulations." in text


def test_summary_when_retention_is_nearly_worthless_points_back_to_acquisition():
    weak = half(extra_orders=0.1)
    text = sc.summarize(weak, exact_sim(weak), 0, 12, "margin")
    assert "best move was about 20% of the budget toward winning new customers" in text


def test_summary_says_so_when_the_best_move_is_at_the_edge_of_what_is_tested():
    # With no diminishing returns the gain keeps rising, so the best move is the 50 percent cap.
    text = sc.summarize(BASE, exact_sim(BASE), 10, 12, "revenue")
    assert "about 50% of the budget toward retention" in text
    assert "That is the largest move this tool tests, so the best size may be larger." in text
    assert "check the cost figures it depends on" in text


def test_summary_does_not_claim_an_edge_when_the_best_move_is_inside_the_range():
    text = sc.summarize(half(), exact_sim(half()), 10, 12, "revenue")
    assert "largest move this tool tests" not in text


def test_the_caveats_warn_about_customers_who_return_on_their_own():
    assert any("come back on their own" in line and "overstate" in line for line in sc.CAVEATS)


def test_money_formatting():
    assert sc._money(1234.4) == "1,234" and sc._money(-1234.6) == "-1,235" and sc._money(0) == "0"


def test_assumptions_table_marks_each_source(frame):
    obs = sc.observed_inputs(frame, 3)
    inputs = Inputs(budget=1000, acquisition_share=0.8, cost_to_win=50, cost_to_bring_back=20, value_new=obs["value_new"],
                    extra_orders=obs["extra_orders"], order_value=obs["order_value"])
    table = sc.assumptions_table(inputs, sc.ranges_from_pct(inputs), obs, 3, {"budget", "acquisition_share", "cost_to_win", "cost_to_bring_back"})
    assert list(table.columns) == ["Assumption", "Value", "Source", "How it is used"] and len(table) == 9
    sources = dict(zip(table["Assumption"], table["Source"]))
    assert sources["Budget over the horizon"] == "You entered it"
    assert sources["Cost to bring one customer back"] == "You entered it"
    assert sources["Value of one order"] == "Observed in your orders"
    assert sources["Diminishing returns exponent"] == "Default, change it"
    assert sources["Uncertainty ranges"] == "Default, change it"


def test_caveats_follow_the_writing_rules():
    assert len(sc.CAVEATS) >= 5
    for line in sc.CAVEATS:
        assert line.endswith(".") and "(" not in line and "—" not in line and "–" not in line
