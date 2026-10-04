"""Synthetic messy order export for the demo.

Everything here is invented. The customers, orders, amounts and the buying
patterns come from a seeded random generator and describe no real business.
The holiday bump in new customers and the repeat decay are modeling choices
made for the demo, not statistics.

Run `python -m src.sample_data` to write data/synthetic_orders_messy.csv.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SYNTHETIC_NOTICE = "Synthetic demo data generated for this project. It is not a real business."
DEFAULT_SEED = 42
DEFAULT_CUSTOMERS = 1500
START = datetime(2024, 1, 1)
END = datetime(2025, 12, 31, 23, 59, 59)
DEFAULT_PATH = Path(__file__).parent.parent / "data" / "synthetic_orders_messy.csv"

STATUSES = ["paid", "pending", "partially_refunded", "refunded", "voided", "cancelled"]
STATUS_WEIGHTS = [0.88, 0.02, 0.02, 0.04, 0.02, 0.02]
DROPPED_STATUSES = {"refunded", "voided", "cancelled"}

LOYAL_SHARE = 0.10
LOYAL_REPEAT_P = 0.88
LOYAL_GAP_DAYS = 40
REGULAR_FIRST_REPEAT_P = 0.35
REGULAR_DECAY = 0.65
REGULAR_GAP_DAYS = 75

BLANK_EMAIL_P = 0.025
GUEST_P = 0.005
UNREADABLE_DATE_P = 0.004
UNREADABLE_VALUE_P = 0.003
ZERO_VALUE_P = 0.006
BULK_ORDER_P = 0.005
EXTRA_LINE_P = (0.12, 0.04)

UNREADABLE_DATES = ["not available", "TBD", "", " "]
TZ_SUFFIXES = ["+0000", "-0500", "+0200", "-0800"]


def _customer_email(idx: int) -> str:
    return f"customer{idx:04d}@example.com"


def _format_date(rng: np.random.Generator, when: datetime) -> str:
    kind = rng.choice(7, p=[0.35, 0.15, 0.10, 0.10, 0.15, 0.08, 0.07])
    if kind == 0:
        return when.strftime("%Y-%m-%d %H:%M:%S ") + "+0000"
    if kind == 1:
        return when.strftime("%Y-%m-%dT%H:%M:%SZ")
    if kind == 2:
        return when.strftime("%Y-%m-%d %H:%M:%S UTC")
    if kind == 3:
        return when.strftime("%Y-%m-%d %H:%M:%S ") + str(rng.choice(TZ_SUFFIXES))
    if kind == 4:
        return when.strftime("%m/%d/%Y %H:%M")
    if kind == 5:
        return when.strftime("%d %b %Y")
    return when.strftime("%b %d, %Y")


def _format_money(rng: np.random.Generator, cents: int) -> str:
    value = cents / 100
    if value >= 1000 and rng.random() < 0.6:
        return f"${value:,.2f}" if rng.random() < 0.5 else f"{value:,.2f}"
    kind = rng.choice(4, p=[0.6, 0.25, 0.08, 0.07])
    if kind == 0:
        return f"{value:.2f}"
    if kind == 1:
        return f"${value:.2f}"
    if kind == 2:
        return f"USD {value:.2f}"
    return f"{value:.2f}".replace(".", ",") if value < 1000 else f"{value:.2f}"


def _format_status(rng: np.random.Generator, status: str) -> str:
    roll = rng.random()
    if roll < 0.20:
        return status.title()
    if roll < 0.25:
        return status.upper()
    return status


def _order_dates(rng: np.random.Generator, n_customers: int) -> list[datetime]:
    days = (END - START).days
    weights = np.array([1.5 if (START + timedelta(days=d)).month in (11, 12) else 1.0 for d in range(days)])
    picks = rng.choice(days, size=n_customers, p=weights / weights.sum())
    secs = rng.integers(0, 86400, size=n_customers)
    return [START + timedelta(days=int(d), seconds=int(s)) for d, s in zip(picks, secs)]


def _split_cents(rng: np.random.Generator, total: int, parts: int) -> list[int]:
    if parts == 1:
        return [total]
    cuts = np.sort(rng.integers(1, total, size=parts - 1))
    pieces = np.diff(np.concatenate([[0], cuts, [total]]))
    return [int(p) for p in pieces]


def generate_orders(seed: int = DEFAULT_SEED, n_customers: int = DEFAULT_CUSTOMERS) -> tuple[pd.DataFrame, dict]:
    """Return the messy export and a truth dict of what a correct cleaning should find."""
    rng = np.random.default_rng(seed)
    first_dates = _order_dates(rng, n_customers)
    loyal = rng.random(n_customers) < LOYAL_SHARE

    # Build the clean order list first, then add the mess.
    orders: list[dict] = []
    for idx in range(n_customers):
        base = float(np.exp(rng.normal(np.log(40), 0.35)))
        when, k = first_dates[idx], 0
        while True:
            total = int(round(base * float(np.exp(rng.normal(0, 0.25))) * 100))
            if rng.random() < BULK_ORDER_P:
                total = int(rng.integers(100000, 300000))
            orders.append({"customer": idx, "when": when, "cents": max(total, 300)})
            p = LOYAL_REPEAT_P if loyal[idx] else REGULAR_FIRST_REPEAT_P * REGULAR_DECAY ** k
            if rng.random() > p:
                break
            mean_gap = LOYAL_GAP_DAYS if loyal[idx] else REGULAR_GAP_DAYS
            when = when + timedelta(days=float(rng.gamma(3.0, mean_gap / 3.0)) + 1)
            if when > END:
                break
            k += 1
    orders.sort(key=lambda o: o["when"])

    rows: list[dict] = []
    truth = {
        "rows": 0, "orders": len(orders), "customers": n_customers, "valid_orders": 0,
        "valid_customers": 0, "valid_revenue": 0.0, "unreadable_date_orders": 0,
        "unreadable_value_orders": 0, "zero_value_orders": 0, "dropped_status_orders": 0,
        "blank_customer_orders": 0, "partial_refund_orders": 0, "multi_line_orders": 0,
    }
    valid_customers: set[int] = set()
    for number, o in enumerate(orders, start=1001):
        status = str(rng.choice(STATUSES, p=STATUS_WEIGHTS))
        roll = rng.random()
        if roll < BLANK_EMAIL_P:
            email, customer_ok = "", False
        elif roll < BLANK_EMAIL_P + GUEST_P:
            email, customer_ok = "Guest", False
        else:
            email = _customer_email(o["customer"])
            if rng.random() < 0.15:
                email = email.capitalize()
            customer_ok = True
        date_ok = rng.random() >= UNREADABLE_DATE_P
        value_text_ok = rng.random() >= UNREADABLE_VALUE_P
        zero = rng.random() < ZERO_VALUE_P

        cents = o["cents"]
        n_lines = 1
        if not zero and value_text_ok:
            n_lines += int(rng.random() < EXTRA_LINE_P[0]) + int(rng.random() < EXTRA_LINE_P[1])
        line_cents = [0] if zero else _split_cents(rng, cents, n_lines) if n_lines > 1 else [cents]
        created = _format_date(rng, o["when"]) if date_ok else str(rng.choice(UNREADABLE_DATES))
        fulfilled = (o["when"] + timedelta(days=int(rng.integers(1, 6)))).strftime("%Y-%m-%d")

        for line_no, lc in enumerate(line_cents):
            rows.append({
                "Order Number": f"#{number}",
                "Email": email,
                "Financial Status": _format_status(rng, status),
                "Created at": created,
                "Fulfilled at": fulfilled,
                "Line Total": _format_money(rng, lc) if value_text_ok else "n/a",
                "Lineitem quantity": int(rng.integers(1, 4)),
                "Lineitem name": f"Sample item {int(rng.integers(1, 12)):02d}",
                "Billing Name": f"Customer {o['customer']:04d}",
                "Billing Phone": f"555-01{o['customer'] % 100:02d}",
                "Shipping Method": str(rng.choice(["Standard", "Express", "Pickup"])),
                "Shipping": "5.00" if line_no == 0 else "0.00",
                "Taxes": "0.00",
                "Discount Amount": "0.00",
                "Accepts Marketing": str(rng.choice(["yes", "no"])),
                "Notes": "Synthetic demo order",
            })

        dropped = status in DROPPED_STATUSES
        truth["unreadable_date_orders"] += not date_ok
        truth["unreadable_value_orders"] += not value_text_ok
        truth["zero_value_orders"] += zero
        truth["dropped_status_orders"] += dropped
        truth["blank_customer_orders"] += not customer_ok
        truth["partial_refund_orders"] += status == "partially_refunded"
        truth["multi_line_orders"] += n_lines > 1
        if date_ok and value_text_ok and not zero and not dropped and customer_ok:
            truth["valid_orders"] += 1
            truth["valid_revenue"] += cents / 100
            valid_customers.add(o["customer"])

    truth["rows"] = len(rows)
    truth["valid_customers"] = len(valid_customers)
    df = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)  # newest first, like a store export
    return df, truth


def write_sample(path: Path = DEFAULT_PATH, overwrite: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path.name} already exists. Delete it or pass overwrite=True to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    df, _ = generate_orders()
    df.to_csv(path, index=False, encoding="utf-8")
    return path


if __name__ == "__main__":
    try:
        out = write_sample()
    except FileExistsError as err:
        sys.exit(str(err))
    print(f"Wrote {out}")
    print(SYNTHETIC_NOTICE)
