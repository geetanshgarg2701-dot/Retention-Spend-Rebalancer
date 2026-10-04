"""Budget scenario: what could happen if some budget moves from winning customers to keeping them.

Everything here is an estimate that rests on stated assumptions. The orders show what
customers were worth and how many repeat orders returning customers placed. They cannot
show whether retention spend works, so the cost to bring a customer back is entered by
the owner, and the diminishing returns exponent is an assumption, not a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from src.metrics import value_curve

DEFAULT_EXPONENT = 0.8
DEFAULT_UNCERTAINTY = 0.25
DEFAULT_DRAWS = 2000
DEFAULT_SEED = 42
HORIZON_CHOICES = (6, 12, 24)
MAX_SHIFT_BACK = 25  # percent of the total budget that may move toward acquisition
MAX_SHIFT_FORWARD = 50  # percent of the total budget that may move toward retention
MIN_EXPONENT = 0.1
REFERENCE_SHARE = 0.10  # reference spend when today's spend on a channel is zero


@dataclass(frozen=True)
class Inputs:
    budget: float  # total marketing budget over the horizon
    acquisition_share: float  # share of the budget spent on winning new customers today, 0 to 1
    cost_to_win: float  # cost to win one new customer
    cost_to_bring_back: float  # cost to bring one customer back
    value_new: float  # value of a new customer over the horizon, observed in the orders
    extra_orders: float  # extra orders a brought-back customer places, observed in the orders by default
    order_value: float  # value of one order, observed in the orders
    exponent: float = DEFAULT_EXPONENT  # diminishing returns, 1 means none


@dataclass(frozen=True)
class Ranges:
    """Low and high for each uncertain input. The mode is the value in Inputs."""
    cost_to_win: tuple[float, float]
    cost_to_bring_back: tuple[float, float]
    extra_orders: tuple[float, float]
    exponent: tuple[float, float]


def validate(inputs: Inputs) -> None:
    if inputs.budget <= 0:
        raise ValueError("The budget must be above zero.")
    if not 0 <= inputs.acquisition_share <= 1:
        raise ValueError("The acquisition share must be between 0 and 100 percent.")
    if inputs.cost_to_win <= 0 or inputs.cost_to_bring_back <= 0:
        raise ValueError("The cost to win a customer and the cost to bring one back must both be above zero.")
    if inputs.value_new < 0 or inputs.extra_orders < 0 or inputs.order_value < 0:
        raise ValueError("Customer value, extra orders and order value cannot be negative.")
    if not MIN_EXPONENT <= inputs.exponent <= 1:
        raise ValueError(f"The diminishing returns exponent must be between {MIN_EXPONENT} and 1.")


def ranges_from_pct(inputs: Inputs, pct: float = DEFAULT_UNCERTAINTY) -> Ranges:
    """Plus or minus pct around each uncertain input. The exponent is kept inside its allowed span."""
    if not 0 <= pct < 1:
        raise ValueError("The uncertainty must be between 0 and 99 percent.")

    def span(value: float) -> tuple[float, float]:
        return value * (1 - pct), value * (1 + pct)

    exp_low, exp_high = span(inputs.exponent)
    return Ranges(
        cost_to_win=span(inputs.cost_to_win),
        cost_to_bring_back=span(inputs.cost_to_bring_back),
        extra_orders=span(inputs.extra_orders),
        exponent=(max(MIN_EXPONENT, exp_low), min(1.0, exp_high)),
    )


def check_ranges(inputs: Inputs, ranges: Ranges) -> None:
    for name, (low, high), mode in (
        ("cost to win", ranges.cost_to_win, inputs.cost_to_win),
        ("cost to bring back", ranges.cost_to_bring_back, inputs.cost_to_bring_back),
        ("extra orders", ranges.extra_orders, inputs.extra_orders),
        ("exponent", ranges.exponent, inputs.exponent),
    ):
        if not low <= mode <= high:
            raise ValueError(f"The {name} range must include the value you entered.")
    if ranges.cost_to_win[0] <= 0 or ranges.cost_to_bring_back[0] <= 0:
        raise ValueError("Cost ranges must stay above zero.")
    if ranges.exponent[0] < MIN_EXPONENT or ranges.exponent[1] > 1:
        raise ValueError(f"The exponent range must stay between {MIN_EXPONENT} and 1.")


# ------------------------------------------------------------------ the model

def allowed_shift_pct(acquisition_share: float) -> tuple[int, int]:
    """Whole percent of the total budget that can move, as a low and a high. Positive moves toward retention."""
    low = -int(np.floor(min(MAX_SHIFT_BACK, (1 - acquisition_share) * 100) + 1e-9))
    high = int(np.floor(min(MAX_SHIFT_FORWARD, acquisition_share * 100) + 1e-9))
    return low, high


def _reference(spend: float, budget: float) -> float:
    return spend if spend > 0 else REFERENCE_SHARE * budget


def customers_from(spend, reference_spend: float, cost: float, exponent):
    """Customers reached with a given spend. Calibrated so reference_spend reaches reference_spend / cost."""
    return (reference_spend / cost) * (np.asarray(spend) / reference_spend) ** exponent


def evaluate(inputs: Inputs, shift: float) -> dict:
    """Spend, customers and total value when shift of the total budget moves toward retention."""
    validate(inputs)
    acq0 = inputs.acquisition_share * inputs.budget
    ret0 = inputs.budget - acq0
    acq, ret = acq0 - shift * inputs.budget, ret0 + shift * inputs.budget
    if acq < -1e-9 or ret < -1e-9:
        raise ValueError("That shift would take a channel below zero spend.")
    acq, ret = max(acq, 0.0), max(ret, 0.0)
    new = float(customers_from(acq, _reference(acq0, inputs.budget), inputs.cost_to_win, inputs.exponent))
    back = float(customers_from(ret, _reference(ret0, inputs.budget), inputs.cost_to_bring_back, inputs.exponent))
    value_back = inputs.extra_orders * inputs.order_value
    return {
        "acquisition_spend": acq, "retention_spend": ret, "new_customers": new, "brought_back": back,
        "value_from_new": new * inputs.value_new, "value_from_brought_back": back * value_back,
        "total_value": new * inputs.value_new + back * value_back,
    }


def delta_value(inputs: Inputs, shift: float) -> float:
    return evaluate(inputs, shift)["total_value"] - evaluate(inputs, 0.0)["total_value"]


def best_shift(inputs: Inputs) -> dict:
    """The whole-percent shift with the largest gain under these exact inputs."""
    low, high = allowed_shift_pct(inputs.acquisition_share)
    gains = {pct: delta_value(inputs, pct / 100) for pct in range(low, high + 1)}
    pct = max(gains, key=lambda p: (gains[p], -abs(p)))  # ties go to the smaller move
    return {"shift": pct / 100, "delta": gains[pct]}


# ----------------------------------------------------------------- simulation

@dataclass
class SimulationResult:
    shifts: np.ndarray  # shares of the total budget, whole percents
    p10: np.ndarray
    median: np.ndarray
    p90: np.ndarray
    prob_positive: np.ndarray
    best_median: float
    best_p10: float
    best_p90: float
    share_best_is_move: float  # share of draws where moving some budget beat keeping the split
    draws: int
    seed: int


def _draw(rng: np.random.Generator, low: float, mode: float, high: float, draws: int) -> np.ndarray:
    if high - low < 1e-12:
        return np.full(draws, mode, dtype=float)
    return rng.triangular(low, mode, high, size=draws)


def simulate(
    inputs: Inputs, ranges: Optional[Ranges] = None, draws: int = DEFAULT_DRAWS, seed: int = DEFAULT_SEED,
) -> SimulationResult:
    """Vary the uncertain inputs inside their ranges and summarize the gain from every possible shift.

    Draws are triangular between low and high with the entered value as the peak. The seed is fixed,
    so the same inputs always give the same answer.
    """
    validate(inputs)
    ranges = ranges or ranges_from_pct(inputs)
    check_ranges(inputs, ranges)
    rng = np.random.default_rng(seed)
    cost_win = _draw(rng, ranges.cost_to_win[0], inputs.cost_to_win, ranges.cost_to_win[1], draws)
    cost_back = _draw(rng, ranges.cost_to_bring_back[0], inputs.cost_to_bring_back, ranges.cost_to_bring_back[1], draws)
    extra = _draw(rng, ranges.extra_orders[0], inputs.extra_orders, ranges.extra_orders[1], draws)
    expo = _draw(rng, ranges.exponent[0], inputs.exponent, ranges.exponent[1], draws)

    low, high = allowed_shift_pct(inputs.acquisition_share)
    pcts = np.arange(low, high + 1)
    shifts = pcts / 100
    acq0 = inputs.acquisition_share * inputs.budget
    ret0 = inputs.budget - acq0
    acq = np.maximum(acq0 - shifts * inputs.budget, 0.0)
    ret = np.maximum(ret0 + shifts * inputs.budget, 0.0)
    acq_ref, ret_ref = _reference(acq0, inputs.budget), _reference(ret0, inputs.budget)

    new = (acq_ref / cost_win)[:, None] * (acq[None, :] / acq_ref) ** expo[:, None]
    back = (ret_ref / cost_back)[:, None] * (ret[None, :] / ret_ref) ** expo[:, None]
    total = new * inputs.value_new + back * (extra * inputs.order_value)[:, None]
    gain = total - total[:, [int(np.where(pcts == 0)[0][0])]]

    best = shifts[gain.argmax(axis=1)]
    p10, median, p90 = np.percentile(gain, [10, 50, 90], axis=0)
    b10, b50, b90 = np.percentile(best, [10, 50, 90])
    return SimulationResult(
        shifts=shifts, p10=p10, median=median, p90=p90, prob_positive=(gain > 1e-9).mean(axis=0),
        best_median=float(b50), best_p10=float(b10), best_p90=float(b90),
        share_best_is_move=float((best != 0).mean()), draws=draws, seed=seed,
    )


# ----------------------------------------------------------- observed from orders

def observed_inputs(frame: pd.DataFrame, horizon_months: int, margin_pct: Optional[float] = None) -> dict:
    """What the orders show: value per new customer, extra orders per repeat customer, and order value."""
    if horizon_months < 1:
        raise ValueError("The horizon must be at least one month.")
    curve = value_curve(frame, margin_pct)
    column = "margin_per_customer" if "margin_per_customer" in curve else "revenue_per_customer"
    wanted = horizon_months - 1
    last = int(curve["month"].max())
    month = min(wanted, last)
    counts = frame.groupby("customer_id").size()
    repeaters = counts[counts >= 2]
    factor = 1.0 if margin_pct is None else margin_pct / 100
    return {
        "value_new": float(curve.loc[curve["month"] == month, column].iloc[0]),
        "value_new_month": month,
        "history_short": wanted > last,
        "extra_orders": float((repeaters - 1).mean()) if len(repeaters) else 0.0,
        "repeat_customers": int(len(repeaters)),
        "order_value": float(frame["order_value"].mean()) * factor,
        "basis": "margin" if margin_pct is not None else "revenue",
    }


# ------------------------------------------------------------------- the report

def _money(value: float) -> str:
    return f"-{abs(value):,.0f}" if value < 0 else f"{value:,.0f}"


def summarize(inputs: Inputs, sim: SimulationResult, shift_pct: int, horizon_months: int, basis: str) -> str:
    """Plain sentences from the numbers. Every one says it is an estimate."""
    idx = int(np.where(np.round(sim.shifts * 100).astype(int) == shift_pct)[0][0])
    median, p10, p90, prob = float(sim.median[idx]), float(sim.p10[idx]), float(sim.p90[idx]), float(sim.prob_positive[idx])
    if shift_pct == 0:
        first = "Keeping today's split is the baseline, so there is no change to estimate."
    else:
        direction = "to retention" if shift_pct > 0 else "to winning new customers"
        verb = "add" if median >= 0 else "lose"
        first = (
            f"Under your assumptions, moving {abs(shift_pct)}% of the budget {direction} is estimated to {verb} "
            f"about {_money(abs(median))} in {basis} over {horizon_months} months, with a range of "
            f"{_money(p10)} to {_money(p90)}. It beat today's split in {prob:.0%} of {sim.draws:,} simulations."
        )
    best = round(sim.best_median * 100)
    if best == 0 and sim.share_best_is_move < 0.5:
        second = "Keeping today's split was the best choice in most simulations."
    else:
        toward = "retention" if best > 0 else "winning new customers"
        second = (
            f"Across the simulations the best move was about {abs(best)}% of the budget toward {toward}, with a "
            f"range of {round(sim.best_p10 * 100)}% to {round(sim.best_p90 * 100)}%."
        )
        edges = (round(float(sim.shifts.min()) * 100), round(float(sim.shifts.max()) * 100))
        if best != 0 and best in edges:
            second += (
                " That is the largest move this tool tests, so the best size may be larger. It suggests one channel "
                "looks much better per dollar under your assumptions, so check the cost figures it depends on."
            )
    return f"{first} {second} These are estimates that depend on your assumptions. They are not a forecast."


def assumptions_table(inputs: Inputs, ranges: Ranges, observed: dict, horizon_months: int, entered: set[str]) -> pd.DataFrame:
    """Every input, where it came from, and what it does. entered holds the names the owner typed in."""
    def source(name: str, observed_name: bool = False) -> str:
        if name in entered:
            return "You entered it"
        return "Observed in your orders" if observed_name else "Default, change it"

    rows = [
        ("Budget over the horizon", f"{inputs.budget:,.0f}", source("budget"), "The total that is split between the two channels."),
        ("Share spent on winning customers today", f"{inputs.acquisition_share:.0%}", source("acquisition_share"), "Sets today's split, the baseline everything is compared with."),
        ("Cost to win one customer", f"{inputs.cost_to_win:,.2f}", source("cost_to_win"), "Turns acquisition spend into new customers."),
        ("Cost to bring one customer back", f"{inputs.cost_to_bring_back:,.2f}", source("cost_to_bring_back"), "Turns retention spend into brought-back customers. Orders cannot measure this, so it is your assumption."),
        (f"Value of a new customer over {horizon_months} months", f"{inputs.value_new:,.2f}", source("value_new", True), f"Counted in {observed['basis']}. Taken from month {observed['value_new_month'] + 1} of your value curve."),
        ("Extra orders from a brought-back customer", f"{inputs.extra_orders:.2f}", source("extra_orders", True), "By default the average extra orders your repeat customers placed in the file."),
        ("Value of one order", f"{inputs.order_value:,.2f}", source("order_value", True), f"Counted in {observed['basis']}. Average order in your file."),
        ("Diminishing returns exponent", f"{inputs.exponent:.2f}", source("exponent"), "Below 1, doubling spend gives less than double the customers. An illustrative assumption, not a measurement."),
        ("Uncertainty ranges", f"{_pct_text(inputs, ranges)}", source("ranges"), "The simulation draws cost, extra orders and the exponent from these ranges."),
    ]
    return pd.DataFrame(rows, columns=["Assumption", "Value", "Source", "How it is used"])


def _pct_text(inputs: Inputs, ranges: Ranges) -> str:
    return (
        f"cost to win {ranges.cost_to_win[0]:,.2f} to {ranges.cost_to_win[1]:,.2f}, "
        f"cost to bring back {ranges.cost_to_bring_back[0]:,.2f} to {ranges.cost_to_bring_back[1]:,.2f}, "
        f"extra orders {ranges.extra_orders[0]:.2f} to {ranges.extra_orders[1]:.2f}, "
        f"exponent {ranges.exponent[0]:.2f} to {ranges.exponent[1]:.2f}"
    )


CAVEATS = [
    "The orders cannot show whether retention spend works. The cost to bring a customer back is your assumption.",
    "Customers who come back on their own may be worth more than customers you pay to bring back. The default for extra "
    "orders comes from customers who returned on their own, so it may overstate what a brought-back customer is worth. "
    "Lower it in the advanced assumptions if you think so.",
    "Each channel is assumed to cost the same per customer at any spend, apart from the diminishing returns setting.",
    "Seasonality, price changes and overlap between the two channels are ignored.",
    "Customers won late in the period are treated as if they had the whole horizon to order.",
    "The simulation spreads out only the inputs listed in the assumptions table. Other uncertainty is not included.",
]
