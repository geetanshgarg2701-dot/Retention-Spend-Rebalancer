import numpy as np
import pandas as pd
import pytest

from src.parsing import infer_date_order, nonblank, parse_dates, strip_tz, to_number


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$1,234.50", 1234.50),
        ("1.234,50", 1234.50),
        ("12,50", 12.50),
        ("1,234", 1234.0),
        ("USD 99", 99.0),
        ("€ 45.00", 45.0),
        ("(20.00)", -20.0),
        ("-15", -15.0),
        ("15-", -15.0),
        ("0", 0.0),
        ("  7.5  ", 7.5),
    ],
)
def test_money_formats(text, expected):
    assert to_number(pd.Series([text])).iloc[0] == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", "2024-01-05", "12/05/2024", "N/A", None])
def test_money_unreadable_becomes_nan(text):
    assert np.isnan(to_number(pd.Series([text])).iloc[0])


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2024-03-05 14:30:00 UTC", "2024-03-05 14:30:00"),
        ("2024-03-05 14:30:00 +0200", "2024-03-05 14:30:00"),
        ("2024-03-05 14:30:00 -05:00", "2024-03-05 14:30:00"),
        ("2024-03-05T14:30:00Z", "2024-03-05T14:30:00"),
        ("2024-03-05T14:30:00+02:00", "2024-03-05T14:30:00"),
        ("2024-03-05 14:30:00+0200", "2024-03-05 14:30:00"),
        ("2024-03-05", "2024-03-05"),
    ],
)
def test_strip_tz_keeps_clock_time(text, expected):
    assert strip_tz(text) == expected


def test_parse_dates_ignores_zone_and_flags_bad_values():
    s = pd.Series(["2024-03-05 14:30:00 UTC", "not a date", "", None, "2024-03-06T01:00:00+02:00"])
    out = parse_dates(s)
    assert out.iloc[0] == pd.Timestamp("2024-03-05 14:30:00")
    assert out.iloc[4] == pd.Timestamp("2024-03-06 01:00:00")
    assert out.iloc[1:4].isna().all()


def test_infer_day_first_when_first_part_exceeds_12():
    assert infer_date_order(pd.Series(["25/03/2024", "01/02/2024"])) == ("day", True)


def test_infer_month_first_when_second_part_exceeds_12():
    assert infer_date_order(pd.Series(["03/25/2024", "01/02/2024"])) == ("month", True)


def test_infer_unknown_when_ambiguous():
    assert infer_date_order(pd.Series(["01/02/2024", "03/04/2024"])) == ("unknown", True)


def test_infer_no_numeric_dates():
    assert infer_date_order(pd.Series(["2024-03-05", "Mar 5 2024"])) == ("unknown", False)


def test_parse_dates_respects_dayfirst():
    s = pd.Series(["03/04/2024"])
    assert parse_dates(s, dayfirst=False).iloc[0] == pd.Timestamp("2024-03-04")
    assert parse_dates(s, dayfirst=True).iloc[0] == pd.Timestamp("2024-04-03")


def test_nonblank_drops_blanks_and_null_words():
    s = pd.Series([" a ", "", "  ", None, "NaN", "none", "null", "b"])
    assert list(nonblank(s)) == ["a", "b"]
