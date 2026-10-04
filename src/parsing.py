"""Small parsing helpers shared by the mapper and the cleaning rules."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

_TZ_SPACE = re.compile(r"\s+(?:Z|UTC|GMT|[+-]\d{2}:?\d{2})$", re.I)
_TZ_COLON = re.compile(r"(?<=\d)(?:Z|[+-]\d{2}:\d{2})$")
_TZ_COMPACT = re.compile(r"(?<=:\d{2})[+-]\d{4}$")
_CURRENCY = re.compile(r"(?i)\b(?:usd|eur|gbp|inr|cad|aud|rs\.?)\b|[$£€₹¥]")
_NUMERIC_SHAPE = re.compile(r"[\d,.\-()]+")
_DAY_MONTH = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})")


def strip_tz(value: str) -> str:
    """Drop a trailing time zone offset without shifting the clock time."""
    v = value.strip()
    for pattern in (_TZ_SPACE, _TZ_COMPACT, _TZ_COLON):
        v = pattern.sub("", v)
    return v


def infer_date_order(values: pd.Series) -> tuple[str, bool]:
    """Return 'day', 'month' or 'unknown', plus whether any numeric d/m dates exist."""
    first_big = second_big = has_numeric = False
    for v in values.astype(str).head(5000):
        m = _DAY_MONTH.match(v)
        if not m:
            continue
        has_numeric = True
        first_big |= int(m.group(1)) > 12
        second_big |= int(m.group(2)) > 12
    if first_big and not second_big:
        return "day", has_numeric
    if second_big and not first_big:
        return "month", has_numeric
    return "unknown", has_numeric


def parse_dates(series: pd.Series, dayfirst: bool = False) -> pd.Series:
    """Parse mixed date strings. Anything unreadable becomes NaT."""
    cleaned = series.astype(object).map(lambda x: strip_tz(x) if isinstance(x, str) else x)
    cleaned = cleaned.map(lambda x: np.nan if isinstance(x, str) and x.strip() == "" else x)
    return pd.to_datetime(cleaned, errors="coerce", dayfirst=dayfirst, format="mixed")


def _to_number(x) -> float:
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return np.nan
    t = str(x).strip()
    if not t:
        return np.nan
    if re.search(r"\d[-/]\d", t):
        return np.nan  # looks like a date or an id, not an amount
    negative = (t.startswith("(") and t.endswith(")")) or t.startswith("-") or t.endswith("-")
    t = _CURRENCY.sub("", t).replace(" ", "").replace("\u00a0", "")
    if not _NUMERIC_SHAPE.fullmatch(t):
        return np.nan
    t = t.replace("(", "").replace(")", "").replace("-", "")
    if not re.search(r"\d", t):
        return np.nan
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            t = parts[0] + "." + parts[1]
        else:
            t = t.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return np.nan
    return -v if negative else v


def to_number(series: pd.Series) -> pd.Series:
    """Turn money-like text into floats. Unreadable values become NaN."""
    return series.map(_to_number).astype(float)


def nonblank(series: pd.Series) -> pd.Series:
    """Non-blank values as stripped text."""
    s = series.dropna().astype(str).str.strip()
    return s[(s != "") & (~s.str.lower().isin({"nan", "none", "null"}))]
