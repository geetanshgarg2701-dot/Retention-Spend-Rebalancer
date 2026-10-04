"""Validate and read an uploaded order export as text."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

MAX_UPLOAD_MB = 25
MAX_ROWS = 500_000
_DELIMITERS = [",", ";", "\t", "|"]


class LoadError(ValueError):
    """A problem with the file that the user can fix. The message is safe to show."""


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _delimiter(text: str) -> str:
    first = text.lstrip("\r\n").split("\n", 1)[0]
    return max(_DELIMITERS, key=first.count)


def read_upload(name: str, data: bytes, max_mb: int = MAX_UPLOAD_MB, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    """Return the file as a frame of text, with blank cells kept as empty strings."""
    if Path(name).suffix.lower() != ".csv":
        raise LoadError("This file is not a CSV. Export your orders as a CSV file and upload that.")
    if len(data) > max_mb * 1024 * 1024:
        raise LoadError(
            f"The file is {len(data) / 1024 / 1024:.1f} MB and the limit is {max_mb} MB. "
            "Export a shorter date range and upload again."
        )
    text = _decode(data)
    if not text.strip():
        raise LoadError("The file is empty. Export your orders again and check that the file has a header row and data rows.")
    try:
        df = pd.read_csv(
            io.StringIO(text), sep=_delimiter(text), dtype=str, keep_default_na=False, nrows=max_rows + 1
        )
    except pd.errors.EmptyDataError:
        raise LoadError("The file is empty. Export your orders again and check that the file has a header row and data rows.") from None
    except (pd.errors.ParserError, ValueError) as err:
        raise LoadError(
            "The file could not be read as a CSV. Check that every row has the same number of columns "
            f"and that every quote is closed. Detail: {str(err)[:150]}"
        ) from None
    if len(df) > max_rows:
        raise LoadError(f"The file has more than {max_rows:,} rows. Export a shorter date range and upload again.")
    if len(df) == 0:
        raise LoadError("The file has a header row but no orders. Export your orders again with the data rows included.")
    df.columns = [str(c).strip() for c in df.columns]
    dupes = sorted({c for c in df.columns if list(df.columns).count(c) > 1})
    if dupes:
        raise LoadError("These column names appear more than once: " + ", ".join(dupes) + ". Rename them in the file and upload again.")
    return df
