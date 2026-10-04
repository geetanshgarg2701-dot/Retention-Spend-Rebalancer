"""Retention spend rebalancer, Week 1: load an order export, confirm columns, review cleaning."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.cleaning import clean_orders, steps_to_frame
from src.loading import MAX_ROWS, MAX_UPLOAD_MB, LoadError, read_upload
from src.mapper import FIELD_HELP, FIELD_LABELS, FIELDS, REQUIRED_FIELDS, gemini_ai_function, map_columns
from src.sample_data import DEFAULT_PATH, SYNTHETIC_NOTICE, generate_orders

NO_COLUMN = "No column"
DATE_CHOICES = {
    "Detect from the data": None,
    "Month first, like 03/14/2025": False,
    "Day first, like 14/03/2025": True,
}
LINE_CHOICES = {
    "Add the line values together": "sum",
    "Use the first line value, for exports where every line repeats the order total": "first",
}
CONFIDENCE_TEXT = {"high": "High confidence", "medium": "Medium confidence", "low": "Low confidence, check this one", "none": "Not matched"}
SESSION_PREFIXES = ("map_", "mapres_", "opt_")
SESSION_KEYS = ("dataset", "stage", "confirmed", "clean", "load_error", "upload_id")

st.set_page_config(page_title="Retention spend rebalancer", layout="wide")


# ------------------------------------------------------------------ state

def reset_state() -> None:
    """Drop everything tied to the current dataset so a new file starts clean."""
    for key in list(st.session_state):
        if key.startswith(SESSION_PREFIXES) or key in SESSION_KEYS:
            del st.session_state[key]


def set_dataset(name: str, raw: pd.DataFrame, source: str, dataset_id: str) -> None:
    st.session_state["dataset"] = {
        "id": dataset_id, "name": name, "raw": raw, "source": source, "synthetic": source == "sample",
    }
    st.session_state["stage"] = 2


def load_sample() -> pd.DataFrame:
    if DEFAULT_PATH.exists():
        return pd.read_csv(DEFAULT_PATH, dtype=str, keep_default_na=False)
    df, _ = generate_orders()
    return df.astype(str)


# ------------------------------------------------------------------ stage 1

def stage_load() -> None:
    st.subheader("1. Load your orders")
    st.write(
        "Upload an order export from your store as a CSV file. "
        "You will confirm how the columns match before anything is cleaned."
    )
    st.session_state.setdefault("upload_n", 0)
    uploaded = st.file_uploader(
        f"CSV file, up to {MAX_UPLOAD_MB} MB and {MAX_ROWS:,} rows",
        type=["csv"], key=f"upload_{st.session_state['upload_n']}",
    )
    if uploaded is not None and uploaded.file_id != st.session_state.get("upload_id"):
        reset_state()
        st.session_state["upload_id"] = uploaded.file_id
        try:
            raw = read_upload(uploaded.name, uploaded.getvalue())
        except LoadError as err:
            st.session_state["load_error"] = str(err)
        else:
            set_dataset(uploaded.name, raw, "upload", uploaded.file_id)
            st.rerun()
    if uploaded is not None and st.session_state.get("load_error"):
        st.error(st.session_state["load_error"])

    st.write("No export to hand? Try the synthetic sample.")
    if st.button("Load the synthetic sample", key="load_sample"):
        reset_state()
        st.session_state["upload_n"] += 1
        set_dataset("synthetic_orders_messy.csv", load_sample(), "sample", "sample")
        st.rerun()
    st.caption(SYNTHETIC_NOTICE)
    privacy_note()


def privacy_note() -> None:
    st.caption(
        "Privacy: your file is processed in this session and is not stored. "
        "If AI matching is on, only column names and up to three masked sample values per column "
        "go to the Gemini API, with emails replaced by a placeholder. "
        "Order rows and customer data are never sent. You can turn AI matching off at any time."
    )


# ------------------------------------------------------------------ stage 2

def get_mapping(ds: dict, use_ai: bool):
    key = f"mapres_{ds['id']}_{use_ai}"
    if key not in st.session_state:
        ai_fn = gemini_ai_function() if use_ai else None
        with st.spinner("Matching columns"):
            st.session_state[key] = map_columns(ds["raw"], ai_fn=ai_fn)
    return st.session_state[key]


def stage_columns() -> None:
    ds = st.session_state["dataset"]
    raw: pd.DataFrame = ds["raw"]
    confirmed = st.session_state.get("confirmed")
    st.subheader("2. Confirm columns")
    if st.button("Load a different file", key="back_to_load"):
        reset_state()
        st.session_state["upload_n"] = st.session_state.get("upload_n", 0) + 1
        st.rerun()
    st.write(f"{ds['name']}: {len(raw):,} rows and {len(raw.columns)} columns.")
    if ds["synthetic"]:
        st.info(SYNTHETIC_NOTICE)

    ai_available = gemini_ai_function() is not None
    use_ai = st.toggle(
        "Use AI to suggest column matches", value=ai_available, disabled=not ai_available, key="use_ai",
        help="Sends only column names and up to three masked sample values per column.",
    )
    if not ai_available:
        st.caption("AI matching is off because no Gemini key is set. The rule-based matches still work.")
    result = get_mapping(ds, use_ai)
    for warning in result.warnings:
        st.warning(warning)

    st.write("Pick the column for each field. Required fields need a column before you can continue.")
    headers = list(raw.columns)
    chosen: dict[str, str] = {}
    for f in FIELDS:
        match = result.matches[f]
        default = confirmed["mapping"].get(f) if confirmed else match.header
        index = headers.index(default) + 1 if default in headers else 0
        left, middle, right = st.columns([2, 1, 4])
        label = FIELD_LABELS[f] + (", required" if f in REQUIRED_FIELDS else "")
        pick = left.selectbox(
            label, [NO_COLUMN] + headers, index=index, key=f"map_{ds['id']}_{use_ai}_{f}", help=FIELD_HELP[f]
        )
        middle.caption(CONFIDENCE_TEXT[match.confidence])
        right.caption(match.reason)
        if pick != NO_COLUMN:
            chosen[f] = pick

    problems = [f"{FIELD_LABELS[f]} needs a column." for f in REQUIRED_FIELDS if f not in chosen]
    used = list(chosen.values())
    for header in sorted({h for h in used if used.count(h) > 1}):
        problems.append(f'The column "{header}" is picked for more than one field. Each field needs its own column.')

    with st.expander("Date format and line item options", expanded=True):
        date_label = st.selectbox(
            "Date format", list(DATE_CHOICES), key=f"opt_{ds['id']}_date",
            index=_index_of(DATE_CHOICES, confirmed["dayfirst"]) if confirmed else 0,
            help="Only matters for dates like 03/04/2025. Detect checks the file for a day above 12.",
        )
        if "order_id" in chosen:
            line_label = st.radio(
                "Orders that span several rows", list(LINE_CHOICES), key=f"opt_{ds['id']}_lines",
                index=_index_of(LINE_CHOICES, confirmed["line_item_mode"]) if confirmed else 0,
            )
        else:
            line_label = next(iter(LINE_CHOICES))
            st.caption("Each row counts as one order, because no order id column is picked.")
        if "quantity" in chosen:
            multiply = st.checkbox(
                "Multiply quantity by the order value, use this when the order value is a unit price",
                value=confirmed["multiply_quantity"] if confirmed else result.multiply_quantity,
                key=f"opt_{ds['id']}_multiply_{use_ai}",
            )
        else:
            multiply = False
            st.caption("Quantity is not used, because no quantity column is picked.")

    for problem in problems:
        st.error(problem)
    if st.button("Confirm columns and clean", key="confirm_columns", disabled=bool(problems), type="primary"):
        options = {
            "mapping": chosen, "dayfirst": DATE_CHOICES[date_label],
            "line_item_mode": LINE_CHOICES[line_label], "multiply_quantity": multiply,
        }
        try:
            outcome = clean_orders(
                raw, chosen, dayfirst=options["dayfirst"],
                line_item_mode=options["line_item_mode"], multiply_quantity=options["multiply_quantity"],
            )
        except ValueError as err:
            st.error(str(err))
            return
        st.session_state["confirmed"] = options
        st.session_state["clean"] = outcome
        st.session_state["stage"] = 3
        st.rerun()
    privacy_note()


def _index_of(choices: dict, value) -> int:
    return list(choices.values()).index(value)


# ------------------------------------------------------------------ stage 3

def stage_review() -> None:
    ds = st.session_state["dataset"]
    frame, steps, warnings, stats = st.session_state["clean"]
    st.subheader("3. Review the cleaning")
    if st.button("Change columns", key="back_to_columns"):
        st.session_state["stage"] = 2
        st.rerun()
    if ds["synthetic"]:
        st.info(SYNTHETIC_NOTICE)

    if stats["orders"]:
        cols = st.columns(4)
        cols[0].metric("Orders", f"{stats['orders']:,}")
        cols[1].metric("Customers", f"{stats['customers']:,}")
        cols[2].metric("Repeat customers", f"{stats['repeat_customer_share']:.0%}")
        cols[3].metric("Total order value", f"{stats['total_revenue']:,.2f}")
        st.caption(
            f"Orders run from {stats['first_date']:%Y-%m-%d} to {stats['last_date']:%Y-%m-%d}. "
            "Total order value is a plain sum of the cleaned values, in the currency the file uses. "
            f"Repeat customers are the share of customers with two or more orders. "
            f"{stats['rows_in']:,} rows went in."
        )
    for warning in warnings:
        st.warning(warning)

    st.markdown("**What cleaning did, rule by rule**")
    st.dataframe(steps_to_frame(steps), hide_index=True, width="stretch")

    if stats["orders"]:
        st.markdown("**Preview of the clean orders**")
        st.dataframe(frame.head(100), hide_index=True, width="stretch")
        csv = frame.to_csv(index=False, float_format="%.2f", date_format="%Y-%m-%d %H:%M:%S")
        st.download_button(
            "Download clean CSV", csv.encode("utf-8"),
            file_name="synthetic_clean_orders.csv" if ds["synthetic"] else "clean_orders.csv",
            mime="text/csv", key="download_clean",
        )
    privacy_note()


# ------------------------------------------------------------------ main

def main() -> None:
    st.title("Retention spend rebalancer")
    st.write(
        "Find out whether to move some ad budget from winning new customers to keeping existing ones. "
        "This is step one of the build: load an order export and clean it, with every decision visible."
    )
    stage = st.session_state.get("stage", 1)
    if "dataset" not in st.session_state:
        stage = 1
    st.caption(f"Step {stage} of 3")
    {1: stage_load, 2: stage_columns, 3: stage_review}[stage]()


main()
