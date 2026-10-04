"""Measure time and peak memory of the whole pipeline on a large synthetic file.

Builds a big CSV outside the repo, runs load, match, clean, metrics, scenario and a DuckDB query on it,
and prints seconds and the process's peak memory after each step. Windows only, because it reads the
process peak working set. Nothing is sent anywhere.
    python scripts/2026-10-04-big-file-check.py wide 150000
    python scripts/2026-10-04-big-file-check.py narrow 500000
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def memory_mb() -> tuple[float, float]:
    """Current and peak working set of this process in megabytes."""
    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError("could not read the process memory")
    return counters.WorkingSetSize / 1e6, counters.PeakWorkingSetSize / 1e6


def build_file(shape: str, rows: int) -> Path:
    from src.sample_data import generate_orders

    base, _ = generate_orders()
    base = base.astype(str)
    reps = rows // len(base) + 1
    pieces = []
    for r in range(reps):
        part = base.copy()
        part["Email"] = part["Email"].where(part["Email"] == "", "r" + str(r) + "_" + part["Email"])
        part["Order Number"] = "#" + str(r) + part["Order Number"]
        pieces.append(part)
    big = pd.concat(pieces, ignore_index=True).iloc[:rows]
    if shape == "narrow":
        big = big[["Email", "Created at", "Line Total", "Financial Status"]]
    path = Path(tempfile.gettempdir()) / f"rsr-big-{shape}-{rows}.csv"
    big.to_csv(path, index=False)
    return path


def step(label: str, fn):
    started = time.perf_counter()
    result = fn()
    now, peak = memory_mb()
    print(f"{label:34} {time.perf_counter() - started:7.1f} s   now {now:7.0f} MB   peak {peak:7.0f} MB", flush=True)
    return result


def main() -> None:
    shape, rows = sys.argv[1], int(sys.argv[2])
    # Import everything the app imports first, so the baseline matches a running app.
    import altair, duckdb, streamlit  # noqa: F401,E401
    from src import askdata, scenario as sc
    from src.cleaning import clean_orders
    from src.loading import read_upload
    from src.mapper import rule_based_map
    from src.metrics import monthly_orders, retention_report

    path = build_file(shape, rows)
    size = os.path.getsize(path) / 1e6
    print(f"file: {shape}, {rows:,} rows, {size:.1f} MB on disk (the upload limit is 25 MB)")
    now, peak = memory_mb()
    print(f"{'baseline after imports':34} {'':>9}   now {now:7.0f} MB   peak {peak:7.0f} MB")
    data = path.read_bytes()
    try:
        raw = step("1 read the upload as text", lambda: read_upload(path.name, data, max_mb=10_000))
    except ValueError as err:
        sys.exit(f"read failed: {err}")
    print(f"{'  raw frame in memory':34} {raw.memory_usage(deep=True).sum() / 1e6:7.0f} MB, {raw.shape[1]} columns")
    del data
    mapping = step("2 match the columns", lambda: rule_based_map(raw))
    result = step("3 clean the orders", lambda: clean_orders(raw, mapping.mapping()))
    clean = result.frame
    print(f"{'  clean frame in memory':34} {clean.memory_usage(deep=True).sum() / 1e6:7.0f} MB, {len(clean):,} orders")
    report = step("4 retention report", lambda: retention_report(clean, 90, 60.0))
    step("5 monthly orders", lambda: monthly_orders(clean))

    def scenario():
        obs = sc.observed_inputs(clean, 12, None)
        inputs = sc.Inputs(budget=10000, acquisition_share=0.8, cost_to_win=60, cost_to_bring_back=25,
                           value_new=obs["value_new"], extra_orders=obs["extra_orders"], order_value=obs["order_value"])
        return sc.simulate(inputs)

    step("6 scenario simulation", scenario)
    step("7 DuckDB question", lambda: askdata.run_preset(clean, "Orders and revenue by month"))
    step("8 DuckDB top customers", lambda: askdata.run_preset(clean, "Top 10 customers by spend"))
    csv = step("9 clean CSV for download", lambda: clean.to_csv(index=False, float_format="%.2f", date_format="%Y-%m-%d %H:%M:%S"))
    print(f"{'  clean CSV size':34} {len(csv) / 1e6:7.1f} MB")
    now, peak = memory_mb()
    print(f"\nPEAK memory of the whole run: {peak:.0f} MB. Streamlit Community Cloud allows 690 MB to 2.7 GB per app.")


if __name__ == "__main__":
    main()
