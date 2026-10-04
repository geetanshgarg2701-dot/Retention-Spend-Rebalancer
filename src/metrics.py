"""Retention numbers computed from the clean order table.

Everything here is observed in the orders. Nothing is projected. Dates are
treated as whole days for recency, and months are calendar months.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_WINDOW_DAYS = 90
WINDOW_CHOICES = (30, 60, 90)
MIN_RFM_CUSTOMERS = 50
MIN_COHORT_MONTHS = 6
TWELVE_MONTH_INDEX = 11

SEGMENT_ORDER = ["Champions", "Loyal", "New", "Occasional", "At risk", "Lapsed"]
SEGMENT_RULES = {
    "New": "First order was within the repeat window, counting back from the last order date in the file.",
    "Champions": "Bought recently and often: recency score 4 or 5 and frequency score 4 or 5.",
    "Loyal": "Bought fairly recently and often: recency score 3 or more and frequency score 3 or more.",
    "At risk": "Used to buy often but has gone quiet: recency score 1 or 2 and frequency score 3 or more.",
    "Lapsed": "Bought rarely and not recently: recency score 1 or 2 and frequency score 1 or 2.",
    "Occasional": "Bought recently but not often: recency score 3 or more and frequency score 1 or 2.",
}


def _month_index(dates: pd.Series) -> pd.Series:
    """Calendar months as one integer, so differences are month counts."""
    return dates.dt.year * 12 + (dates.dt.month - 1)


def _month_label(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def _check(frame: pd.DataFrame) -> pd.DataFrame:
    missing = {"customer_id", "order_date", "order_value"} - set(frame.columns)
    if missing:
        raise ValueError("The clean orders need these columns: " + ", ".join(sorted(missing)) + ".")
    if len(frame) == 0:
        raise ValueError("There are no orders to analyze.")
    return frame.sort_values(["customer_id", "order_date"], kind="stable").reset_index(drop=True)


def _score(values: pd.Series) -> pd.Series:
    """Score 1 to 5 from the tie-aware rank. Higher values score higher."""
    share = values.rank(method="average") / len(values)
    return np.ceil(np.round(5 * share, 9)).clip(1, 5).astype(int)


# --------------------------------------------------------------- repeat purchase

def repeat_metrics(frame: pd.DataFrame, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Repeat rate overall and within a window, plus the typical gap to a second order.

    The window rate only counts customers whose first order is at least window_days
    before the last order in the file, so recent customers are not undercounted.
    """
    df = _check(frame)
    df["n"] = df.groupby("customer_id").cumcount()
    first = df[df["n"] == 0].set_index("customer_id")["order_date"]
    second = df[df["n"] == 1].set_index("customer_id")["order_date"]
    gap_days = ((second - first.reindex(second.index)).dt.total_seconds() / 86400)
    last_date = df["order_date"].max()
    eligible = first[first <= last_date - pd.Timedelta(days=window_days)]
    in_window = gap_days.reindex(eligible.index).le(window_days).sum()
    customers = len(first)
    return {
        "customers": customers,
        "repeat_customers": len(second),
        "repeat_rate": len(second) / customers,
        "window_days": window_days,
        "eligible_customers": len(eligible),
        "repeat_in_window": int(in_window),
        "repeat_in_window_rate": (int(in_window) / len(eligible)) if len(eligible) else None,
        "median_days_to_second": float(gap_days.median()) if len(gap_days) else None,
        "orders": len(df),
        "average_order_value": float(df["order_value"].mean()),
        "last_order_date": last_date,
    }


# ----------------------------------------------------------------------- cohorts

@dataclass
class CohortResult:
    sizes: pd.Series  # customers per cohort, indexed by YYYY-MM
    retention: pd.DataFrame  # share of the cohort active in month k, NaN where not yet observable
    average: pd.Series  # all observable cohorts pooled, indexed by month k
    months_observed: int
    last_month_partial: bool


def cohort_retention(frame: pd.DataFrame) -> CohortResult:
    """Group customers by the month of their first order and track who orders in each later month."""
    df = _check(frame)
    df["ym"] = _month_index(df["order_date"])
    cohort_ym = df.groupby("customer_id")["ym"].transform("min")
    df["k"] = df["ym"] - cohort_ym
    df["cohort"] = cohort_ym
    last_ym = int(df["ym"].max())

    sizes = df.groupby("cohort")["customer_id"].nunique()
    active = df.groupby(["cohort", "k"])["customer_id"].nunique().unstack(fill_value=0)
    max_k = last_ym - sizes.index.to_numpy()
    width = int(max_k.max()) + 1
    active = active.reindex(columns=range(width), fill_value=0)

    retention = pd.DataFrame(np.nan, index=sizes.index, columns=range(width))
    average = {}
    for k in range(width):
        observable = max_k >= k
        retention.loc[observable, k] = active.loc[observable, k] / sizes[observable]
        average[k] = active.loc[observable, k].sum() / sizes[observable].sum()
    labels = [_month_label(int(i)) for i in sizes.index]
    retention.index = labels
    last_date = df["order_date"].max()
    partial = last_date.day < last_date.days_in_month
    return CohortResult(
        sizes=pd.Series(sizes.to_numpy(), index=labels, name="Customers"),
        retention=retention, average=pd.Series(average, name="Pooled"),
        months_observed=width, last_month_partial=bool(partial),
    )


# ------------------------------------------------------------------ order count funnel

FUNNEL_LEVELS = (1, 2, 3, 5)


def order_count_funnel(frame: pd.DataFrame, levels: tuple = FUNNEL_LEVELS) -> pd.DataFrame:
    """How many customers reached each order count, as observed in the file.

    share is the share of all customers. share_of_previous is the share of the
    step before, and is None for the first step.
    """
    df = _check(frame)
    per_customer = df.groupby("customer_id").size()
    total = len(per_customer)
    rows, previous = [], None
    for level in levels:
        count = int((per_customer >= level).sum())
        rows.append({
            "orders": level,
            "customers": count,
            "share": count / total,
            "share_of_previous": None if previous is None else (count / previous if previous else 0.0),
        })
        previous = count
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- RFM

def assign_segment(r: int, f: int, is_new: bool) -> str:
    """The segment rules, in the order they are checked."""
    if is_new:
        return "New"
    if r >= 4 and f >= 4:
        return "Champions"
    if r >= 3 and f >= 3:
        return "Loyal"
    if r <= 2 and f >= 3:
        return "At risk"
    if r <= 2:
        return "Lapsed"
    return "Occasional"


def rfm_table(frame: pd.DataFrame, window_days: int = DEFAULT_WINDOW_DAYS) -> pd.DataFrame:
    """One row per customer with recency, frequency, monetary, 1 to 5 scores and a segment.

    Recency counts back from the last order date in the file, not from today.
    """
    df = _check(frame)
    reference = df["order_date"].max().normalize()
    per = df.groupby("customer_id").agg(
        first_order=("order_date", "min"), last_order=("order_date", "max"),
        frequency=("order_date", "size"), monetary=("order_value", "sum"),
    )
    per["recency_days"] = (reference - per["last_order"].dt.normalize()).dt.days
    days_since_first = (reference - per["first_order"].dt.normalize()).dt.days
    per["r_score"] = _score(-per["recency_days"])
    per["f_score"] = _score(per["frequency"])
    per["m_score"] = _score(per["monetary"])
    per["segment"] = [
        assign_segment(r, f, bool(new))
        for r, f, new in zip(per["r_score"], per["f_score"], days_since_first <= window_days)
    ]
    return per.reset_index()[
        ["customer_id", "recency_days", "frequency", "monetary", "r_score", "f_score", "m_score", "segment"]
    ]


def segment_summary(rfm: pd.DataFrame) -> pd.DataFrame:
    """Customers, share of customers, average orders, average spend and share of revenue per segment."""
    grouped = rfm.groupby("segment").agg(
        customers=("customer_id", "size"), average_orders=("frequency", "mean"),
        average_spend=("monetary", "mean"), revenue=("monetary", "sum"),
    ).reindex(SEGMENT_ORDER).fillna(0)
    grouped["customers"] = grouped["customers"].astype(int)
    grouped["share_of_customers"] = grouped["customers"] / grouped["customers"].sum()
    grouped["share_of_revenue"] = grouped["revenue"] / grouped["revenue"].sum()
    return grouped.drop(columns="revenue")


# ------------------------------------------------------------- value and payback

def value_curve(frame: pd.DataFrame, margin_pct: Optional[float] = None) -> pd.DataFrame:
    """Cumulative revenue per acquired customer, by months since the first order month.

    Month 0 is the month of the first order. Each point uses only customers who have
    had that many months to order, so later months rest on fewer, older customers
    and the line can dip. margin_pct adds a margin column when given.
    """
    if margin_pct is not None and not 0 < margin_pct <= 100:
        raise ValueError("Gross margin must be above 0 and at most 100 percent.")
    df = _check(frame)
    df["ym"] = _month_index(df["order_date"])
    df["k"] = df["ym"] - df.groupby("customer_id")["ym"].transform("min")
    last_ym = int(df["ym"].max())
    cohort = df.groupby("customer_id")["ym"].min()
    max_k = last_ym - cohort
    width = int(max_k.max()) + 1
    cumulative = (
        df.pivot_table(index="customer_id", columns="k", values="order_value", aggfunc="sum", fill_value=0)
        .reindex(index=cohort.index, columns=range(width), fill_value=0)
        .cumsum(axis=1)
    )
    rows = []
    for k in range(width):
        observed = max_k >= k
        rows.append({
            "month": k,
            "customers_observed": int(observed.sum()),
            "revenue_per_customer": float(cumulative.loc[observed, k].mean()),
        })
    out = pd.DataFrame(rows)
    if margin_pct is not None:
        out["margin_per_customer"] = out["revenue_per_customer"] * margin_pct / 100
    return out


def payback(curve: pd.DataFrame, cost_to_win: Optional[float]) -> dict:
    """First month where cumulative value per customer reaches the cost to win one.

    Uses the margin column when it exists, otherwise revenue.
    """
    basis = "margin" if "margin_per_customer" in curve else "revenue"
    if cost_to_win is None:
        return {"basis": basis, "reached": False, "month": None, "entered": False}
    if cost_to_win < 0:
        raise ValueError("The cost to win a customer cannot be negative.")
    column = "margin_per_customer" if basis == "margin" else "revenue_per_customer"
    hit = curve[curve[column] >= cost_to_win]
    return {
        "basis": basis, "entered": True, "reached": len(hit) > 0,
        "month": int(hit["month"].iloc[0]) if len(hit) else None,
    }


def twelve_month_value(curve: pd.DataFrame) -> Optional[float]:
    """Revenue per customer over the first 12 months, only when customers have been observed that long."""
    row = curve[curve["month"] == TWELVE_MONTH_INDEX]
    return float(row["revenue_per_customer"].iloc[0]) if len(row) else None


# ------------------------------------------------------------------- everything

@dataclass
class RetentionReport:
    repeat: dict
    cohorts: CohortResult
    rfm: pd.DataFrame
    segments: pd.DataFrame
    curve: pd.DataFrame
    payback: dict
    twelve_month: Optional[float]
    funnel: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def retention_report(
    frame: pd.DataFrame,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cost_to_win: Optional[float] = None,
    margin_pct: Optional[float] = None,
) -> RetentionReport:
    repeat = repeat_metrics(frame, window_days)
    cohorts = cohort_retention(frame)
    rfm = rfm_table(frame, window_days)
    curve = value_curve(frame, margin_pct)
    warnings: list[str] = []
    if repeat["customers"] < MIN_RFM_CUSTOMERS:
        warnings.append(
            f"Only {repeat['customers']:,} customers. Segment scores are ranks within the file, "
            f"so they are unreliable below {MIN_RFM_CUSTOMERS} customers."
        )
    if cohorts.months_observed < MIN_COHORT_MONTHS:
        warnings.append(
            f"The orders cover only {cohorts.months_observed} months, so the cohort table is short "
            "and later months rest on few customers."
        )
    if cohorts.last_month_partial:
        warnings.append("The last month in the file looks incomplete, so its retention can read low.")
    if repeat["eligible_customers"] == 0:
        warnings.append(
            f"No customer is old enough to measure a {window_days} day repeat rate. "
            "Try a shorter window or a longer date range."
        )
    return RetentionReport(
        repeat, cohorts, rfm, segment_summary(rfm), curve,
        payback(curve, cost_to_win), twelve_month_value(curve), order_count_funnel(frame), warnings,
    )
