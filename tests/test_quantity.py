import pandas as pd
import pytest

from src.quantity import QUANTITY_CHOICES, TOTAL_CHOICE, UNIT_CHOICE, quantity_preview


def frame():
    return pd.DataFrame({
        "price": ["10.00", "$20.00", "30.00", "40.00", "bad", "", "-5.00", "50.00"],
        "qty": ["1", "2", "3", "4", "5", "6", "7", "0"],
    })


def test_the_two_choices_map_to_the_two_readings():
    assert QUANTITY_CHOICES[TOTAL_CHOICE] is False
    assert QUANTITY_CHOICES[UNIT_CHOICE] is True


def test_averages_use_only_rows_with_a_readable_positive_value_and_quantity():
    p = quantity_preview(frame(), "price", "qty")
    # rows used: (10,1) (20,2) (30,3) (40,4). Unreadable, blank, negative and zero quantity rows are skipped.
    assert p.rows_used == 4
    assert p.average_if_total == pytest.approx((10 + 20 + 30 + 40) / 4)
    assert p.average_if_unit == pytest.approx((10 * 1 + 20 * 2 + 30 * 3 + 40 * 4) / 4)


def test_the_examples_show_the_first_three_usable_rows_under_both_readings():
    p = quantity_preview(frame(), "price", "qty")
    assert list(p.examples.columns) == [
        "Order value in the file", "Quantity in the file", "Line value if a total", "Line value if per item",
    ]
    assert len(p.examples) == 3
    assert p.examples["Line value if a total"].tolist() == [10.0, 20.0, 30.0]
    assert p.examples["Line value if per item"].tolist() == [10.0, 40.0, 90.0]


def test_a_total_and_a_per_item_reading_differ_when_quantities_exceed_one():
    p = quantity_preview(frame(), "price", "qty")
    assert p.average_if_unit > p.average_if_total


def test_quantities_of_one_give_the_same_average_both_ways():
    df = pd.DataFrame({"price": ["5.00", "7.00"], "qty": ["1", "1"]})
    p = quantity_preview(df, "price", "qty")
    assert p.average_if_total == p.average_if_unit == pytest.approx(6.0)


def test_no_usable_rows_returns_none():
    df = pd.DataFrame({"price": ["bad", "", "-1"], "qty": ["1", "2", "3"]})
    assert quantity_preview(df, "price", "qty") is None
