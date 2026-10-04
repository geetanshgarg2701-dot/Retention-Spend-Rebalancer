"""Turn a raw order export into a clean order table and record every decision."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple, Optional

import numpy as np
import pandas as pd

from src.parsing import infer_date_order, parse_dates, to_number

MIN_ORDERS = 200
MIN_CUSTOMERS = 50
MIN_SPAN_DAYS = 90
MAX_REMOVED_SHARE = 0.30

LINE_ITEM_MODES = ("sum", "first")

_FULL_LOSS_STATUS = re.compile(
    r"\b(?:refund(?:ed)?|void(?:ed)?|cancel(?:l?ed)?|fail(?:ed|ure)?|return(?:ed)?"
    r"|charge ?back(?:s|ed)?)\b"
)
_PLACEHOLDER_CUSTOMERS = {
    "", "nan", "none", "null", "na", "n a", "guest", "guest checkout", "guest customer",
    "guest user", "anonymous", "unknown", "not provided", "missing", "no customer",
}


@dataclass
class CleaningStep:
    number: int
    rule: str
    rows_removed: int
    why: str


class CleaningResult(NamedTuple):
    frame: pd.DataFrame
    steps: list[CleaningStep]
    warnings: list[str]
    stats: dict


def steps_to_frame(steps: list[CleaningStep]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Step": s.number, "Rule": s.rule, "Rows removed": s.rows_removed, "Why": s.why} for s in steps]
    )


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _normalize_status(value: object) -> str:
    text = "" if pd.isna(value) else str(value).lower()
    return re.sub(r"[\s_\-]+", " ", text).strip()


def _drops_status(value: object) -> bool:
    text = _normalize_status(value)
    return bool(_FULL_LOSS_STATUS.search(text)) and "partial" not in text


def _clean_customer(series: pd.Series) -> pd.Series:
    def one(v: object) -> str:
        text = "" if pd.isna(v) else str(v).strip()
        return text.lower() if "@" in text else text

    return series.map(one)


def _is_placeholder(value: str) -> bool:
    key = re.sub(r"[\s_\-()\[\]./]+", " ", value.lower()).strip()
    return key in _PLACEHOLDER_CUSTOMERS


def _check_inputs(raw: pd.DataFrame, mapping: dict, line_item_mode: str, multiply_quantity: bool) -> None:
    if line_item_mode not in LINE_ITEM_MODES:
        raise ValueError('The line item mode must be "sum" or "first".')
    missing = [f for f in ("customer_id", "order_date", "order_value") if not mapping.get(f)]
    if missing:
        raise ValueError("Map these fields before cleaning: " + ", ".join(missing) + ".")
    if multiply_quantity and not mapping.get("quantity"):
        raise ValueError("Map a quantity column, or turn off multiplying quantity by price.")
    absent = [h for h in mapping.values() if h and h not in raw.columns]
    if absent:
        raise ValueError("These mapped columns are not in the file: " + ", ".join(absent) + ".")
    if len(raw) == 0:
        raise ValueError("The file has no rows to clean.")


def clean_orders(
    raw: pd.DataFrame,
    mapping: dict,
    dayfirst: Optional[bool] = None,
    line_item_mode: str = "sum",
    multiply_quantity: bool = False,
) -> CleaningResult:
    """Apply the cleaning rules in order and return the clean frame, steps, warnings and stats.

    mapping holds canonical field to header. dayfirst None means infer from the data.
    line_item_mode is "sum" or "first" and only matters when an order id is mapped.
    """
    _check_inputs(raw, mapping, line_item_mode, multiply_quantity)
    rows_in = len(raw)
    warnings: list[str] = []
    steps: list[CleaningStep] = []

    def col(field: str) -> pd.Series:
        return raw[mapping[field]].reset_index(drop=True)

    work = pd.DataFrame({
        "customer_id": _clean_customer(col("customer_id")),
        "raw_date": col("order_date"),
        "raw_value": col("order_value"),
    })
    has_order_id = bool(mapping.get("order_id"))
    if has_order_id:
        work["order_id"] = col("order_id").map(lambda v: "" if pd.isna(v) else str(v).strip())
    if multiply_quantity:
        work["raw_quantity"] = col("quantity")
    if mapping.get("order_status"):
        work["status"] = col("order_status")

    def drop(mask: pd.Series, number: int, rule: str, why: str) -> None:
        nonlocal work
        removed = int(mask.sum())
        work = work[~mask].reset_index(drop=True)
        steps.append(CleaningStep(number, rule, removed, why if removed else "Nothing to remove."))

    # 1. dates
    if dayfirst is None:
        order, has_numeric = infer_date_order(work["raw_date"])
        dayfirst_used = order == "day"
        if order == "unknown" and has_numeric:
            warnings.append(
                "Some dates such as 03/04/2025 could be day first or month first. "
                "Month first was assumed. Change the date format option if that is wrong."
            )
    else:
        dayfirst_used = bool(dayfirst)
    work["order_date"] = parse_dates(work["raw_date"], dayfirst=dayfirst_used)
    bad = work["order_date"].isna()
    drop(bad, 1, "Unreadable dates",
         f"{_plural(int(bad.sum()), 'row')} had a blank or unreadable order date.")

    # 2. values
    value = to_number(work["raw_value"])
    if multiply_quantity:
        value = value * to_number(work["raw_quantity"])
    work["order_value"] = value
    bad = work["order_value"].isna()
    why = f"{_plural(int(bad.sum()), 'row')} had a blank or unreadable order value"
    why += " or quantity." if multiply_quantity else "."
    drop(bad, 2, "Unreadable order values", why)

    # 3. statuses
    if "status" in work:
        mask = work["status"].map(_drops_status).astype(bool)
        why = (f"{_plural(int(mask.sum()), 'row')} had a refunded, voided, cancelled, failed, "
               "returned or chargeback status. Partial refunds were kept.")
    else:
        mask = pd.Series(False, index=work.index)
        why = ""
    drop(mask, 3, "Refunded, voided and cancelled orders", why)
    if "status" not in work:
        steps[-1].why = "No status column was mapped, so nothing was dropped."

    # 4 and 5. negative and zero values
    mask = work["order_value"] < 0
    drop(mask, 4, "Negative values", f"{_plural(int(mask.sum()), 'row')} had a negative order value.")
    mask = work["order_value"] == 0
    drop(mask, 5, "Zero-value orders", f"{_plural(int(mask.sum()), 'row')} had an order value of zero.")

    # 6. customers
    mask = work["customer_id"].map(_is_placeholder).astype(bool)
    drop(mask, 6, "Missing or placeholder customers",
         f"{_plural(int(mask.sum()), 'row')} had a blank or placeholder customer id such as guest. "
         "Emails were lowercased.")

    removed_by_rules = sum(s.rows_removed for s in steps)

    # 7. line items
    columns = ["customer_id", "order_date", "order_value"] + (["order_id"] if has_order_id else [])
    if has_order_id:
        keyed = work["order_id"] != ""
        agg_value = "sum" if line_item_mode == "sum" else "first"
        combined = (
            work[keyed]
            .groupby("order_id", sort=False)
            .agg(customer_id=("customer_id", "first"), order_date=("order_date", "min"),
                 order_value=("order_value", agg_value))
            .reset_index()
        )
        before = len(work)
        work = pd.concat([combined, work.loc[~keyed, columns]], ignore_index=True)
        merged = before - len(work)
        how = "added together" if line_item_mode == "sum" else "taken from the first line"
        steps.append(CleaningStep(
            7, "Repeated order ids combined into one order", merged,
            f"{_plural(merged, 'row')} were extra lines of an order. Line values were {how}."
            if merged else "Nothing to combine.",
        ))
    else:
        steps.append(CleaningStep(7, "Repeated order ids combined into one order", 0,
                                  "No order id column was mapped, so each row counts as one order."))

    # 8. exact duplicates that cannot be told apart from real repeat orders
    candidates = work if not has_order_id else work[work["order_id"] == ""]
    dupes = int(candidates.duplicated(["customer_id", "order_date", "order_value"]).sum())
    steps.append(CleaningStep(
        8, "Exact duplicate rows without an order id", 0,
        f"{_plural(dupes, 'row')} repeat another row exactly and were kept." if dupes else "No exact duplicates found.",
    ))
    if dupes:
        warnings.append(
            f"{_plural(dupes, 'row')} exactly repeat another row and have no order id, so they were kept. "
            "Identical orders can be real, but check the export if this looks too high."
        )

    frame = work[columns].sort_values("order_date", kind="stable").reset_index(drop=True)
    stats = _stats(frame, rows_in)
    warnings.extend(_quality_warnings(stats, removed_by_rules, rows_in))
    stats["dayfirst_used"] = dayfirst_used
    return CleaningResult(frame, steps, warnings, stats)


def _stats(frame: pd.DataFrame, rows_in: int) -> dict:
    orders = len(frame)
    per_customer = frame.groupby("customer_id").size() if orders else pd.Series(dtype=int)
    customers = int(per_customer.size)
    return {
        "rows_in": rows_in,
        "orders": orders,
        "customers": customers,
        "first_date": frame["order_date"].min() if orders else None,
        "last_date": frame["order_date"].max() if orders else None,
        "repeat_customer_share": float((per_customer >= 2).mean()) if customers else 0.0,
        "total_revenue": float(frame["order_value"].sum()) if orders else 0.0,
    }


def _quality_warnings(stats: dict, removed_by_rules: int, rows_in: int) -> list[str]:
    out: list[str] = []
    if stats["orders"] == 0:
        return ["No orders are left after cleaning. Check the column matches and the date format."]
    if stats["orders"] < MIN_ORDERS:
        out.append(f"Only {stats['orders']:,} orders are left. Results from fewer than {MIN_ORDERS} orders are unreliable.")
    if stats["customers"] < MIN_CUSTOMERS:
        out.append(f"Only {stats['customers']:,} customers are left. Results from fewer than {MIN_CUSTOMERS} customers are unreliable.")
    span = (stats["last_date"] - stats["first_date"]).days
    if span < MIN_SPAN_DAYS:
        out.append(f"The orders span {span} days. Retention needs at least {MIN_SPAN_DAYS} days to show repeat buying.")
    if stats["repeat_customer_share"] == 0:
        out.append("No customer ordered more than once, so repeat purchase patterns cannot be measured.")
    share = removed_by_rules / rows_in
    if share > MAX_REMOVED_SHARE:
        out.append(
            f"The cleaning rules dropped {share:.0%} of the rows. "
            "Check the column matches and the steps table before you trust the results."
        )
    return out
