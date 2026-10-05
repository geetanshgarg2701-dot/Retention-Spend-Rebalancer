"""Show what each reading of the order value would do, so the user can check it against the file."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.parsing import to_number

TOTAL_CHOICE = "The order value is the total for the whole order"
UNIT_CHOICE = "The order value is the price of one item, so multiply by quantity"
QUANTITY_CHOICES = {TOTAL_CHOICE: False, UNIT_CHOICE: True}

EXAMPLE_ROWS = 3


@dataclass
class QuantityPreview:
    examples: pd.DataFrame
    average_if_total: float
    average_if_unit: float
    rows_used: int


def quantity_preview(raw: pd.DataFrame, value_header: str, quantity_header: str) -> QuantityPreview | None:
    """The first rows and the average value per row under each reading.

    Only rows with a readable, positive value and quantity are used, so refunds and blanks do not skew it.
    Returns None when no row qualifies.
    """
    value = to_number(raw[value_header])
    qty = to_number(raw[quantity_header])
    ok = (value > 0) & (qty > 0)
    if not ok.any():
        return None
    value, qty = value[ok], qty[ok]
    head = pd.DataFrame({
        "Order value in the file": value.head(EXAMPLE_ROWS),
        "Quantity in the file": qty.head(EXAMPLE_ROWS),
        "Line value if a total": value.head(EXAMPLE_ROWS),
        "Line value if per item": (value * qty).head(EXAMPLE_ROWS),
    }).reset_index(drop=True)
    return QuantityPreview(
        examples=head,
        average_if_total=float(value.mean()),
        average_if_unit=float((value * qty).mean()),
        rows_used=int(ok.sum()),
    )
