"""Retention spend rebalancer: load an order export, confirm columns, review cleaning, see retention results."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import ui
from src.cleaning import clean_orders, steps_to_frame
from src.loading import MAX_ROWS, MAX_UPLOAD_MB, LoadError, read_upload
from src.mapper import FIELD_HELP, FIELD_LABELS, FIELDS, REQUIRED_FIELDS, gemini_ai_function, map_columns
from src.metrics import (
    DEFAULT_WINDOW_DAYS, SEGMENT_ORDER, SEGMENT_RULES, WINDOW_CHOICES, monthly_orders, payback_progress, retention_report,
)
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
SESSION_PREFIXES = ("map_", "mapres_", "opt_")
SESSION_KEYS = ("dataset", "stage", "confirmed", "clean", "load_error", "upload_id", "retention_inputs")

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
    st.html(ui.hero_html(
        eyebrow="Retention analysis for business stores",
        headline="Keep the customers you already paid for",
        lead=(
            "Find out whether to move some ad budget from winning new customers to keeping the ones you have. "
            "Upload your order export and get a plain answer, with every assumption visible."
        ),
        tags=["Observed, not forecast", "Free to run", "Private by default"],
        nodes=["Load orders", "Confirm columns", "Review cleaning", "Retention results"],
    ))
    st.html(ui.points_html([
        ("Clean it", "A messy export is cleaned by eight rules, and you see every row that was removed and why."),
        ("Match it", "Columns are matched for you with a reason for each. You confirm before anything runs."),
        ("Measure it", "Repeat rate, cohorts, segments, customer value and payback, all calculated from your orders."),
    ]))
    st.subheader("Load your orders")
    st.session_state.setdefault("upload_n", 0)
    left, right = st.columns([3, 2], gap="large")
    with left:
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
    with right:
        with st.container(border=True):
            st.markdown("**No export to hand?**")
            st.write("Try the synthetic sample to see the whole flow.")
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
        "go to the Gemini API, with emails and phone-like numbers replaced by placeholders. "
        "Columns that look personal, such as names, phones and addresses, send the column name only. "
        "Order rows and customer data are never sent. "
        "On the free Gemini tier, Google may use what is sent to improve its products, "
        "and people may review it. You can turn AI matching off at any time."
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
    st.subheader("Confirm columns")
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
        left, middle, right = st.columns([2, 2, 4], vertical_alignment="center")
        label = FIELD_LABELS[f] + (", required" if f in REQUIRED_FIELDS else "")
        pick = left.selectbox(
            label, [NO_COLUMN] + headers, index=index, key=f"map_{ds['id']}_{use_ai}_{f}", help=FIELD_HELP[f]
        )
        middle.html(ui.pill_html(match.confidence))
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
    st.subheader("Review the cleaning")
    if st.button("Change columns", key="back_to_columns"):
        st.session_state["stage"] = 2
        st.rerun()
    if ds["synthetic"]:
        st.info(SYNTHETIC_NOTICE)

    if stats["orders"]:
        cols = st.columns(4)
        cols[0].metric("Orders", f"{stats['orders']:,}", border=True)
        cols[1].metric("Customers", f"{stats['customers']:,}", border=True)
        cols[2].metric("Repeat customers", f"{stats['repeat_customer_share']:.0%}", border=True)
        cols[3].metric("Total order value", f"{stats['total_revenue']:,.2f}", border=True)
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
        if st.button("Continue to retention results", key="to_results", type="primary"):
            st.session_state["stage"] = 4
            st.rerun()
    privacy_note()


# ------------------------------------------------------------------ stage 4

def money(value: float) -> str:
    return f"{value:,.2f}"


def command_row(frame: pd.DataFrame, report) -> None:
    """Four overview cards, each built from numbers the metrics module computed.

    The first two use Streamlit's own sparkline, which the HTML sanitizer cannot strip.
    """
    monthly = monthly_orders(frame)
    pooled = report.cohorts.average.iloc[1:]  # month 0 is always 100 percent, so the line starts at month 1
    segments = [(name, int(report.segments.loc[name, "customers"])) for name in SEGMENT_ORDER]
    cost = st.session_state["retention_inputs"]["cost"]
    progress = payback_progress(report.curve, cost)

    first, second, third, fourth = st.columns(4)
    first.metric(
        "Orders per month, on average", f"{monthly.mean():,.0f}", border=True,
        chart_data=monthly.tolist(), chart_type="line",
        help=f"Orders per month from {monthly.index[0]} to {monthly.index[-1]}. The last month may be incomplete.",
    )
    if len(pooled):
        second.metric(
            "Customers back the month after", f"{pooled.iloc[0]:.0%}", border=True,
            chart_data=pooled.tolist(), chart_type="line",
            help="Share of customers who ordered again in their second month, pooled over every cohort that has "
                 "reached it. The line follows the later months.",
        )
    else:
        second.metric("Customers back the month after", "Not enough history", border=True)
    with third.container(border=True):
        st.html(ui.card_html(
            "Customers by segment", f"{sum(n for _, n in segments):,}",
            "Sorted by how recently and how often they bought.", ui.segment_strip_html(segments),
        ))
    with fourth.container(border=True):
        if progress["entered"]:
            note = (
                f"Best {progress['basis']} per customer so far is {money(progress['best_value'])} "
                f"against {money(cost)} to win one."
            )
            st.html(ui.card_html(
                "Payback progress", f"{progress['share']:.0%} of your cost", note,
                ui.progress_html(progress["share"], "Payback progress"),
            ))
        else:
            st.html(ui.card_html("Payback progress", "Enter your cost", "Add what it costs to win one customer in the inputs above."))


def stage_results() -> None:
    ds = st.session_state["dataset"]
    frame = st.session_state["clean"].frame
    st.subheader("Retention results")
    if st.button("Back to the cleaning review", key="back_to_review"):
        st.session_state["stage"] = 3
        st.rerun()
    if ds["synthetic"]:
        st.info(
            SYNTHETIC_NOTICE + " Its repeat buying pattern comes from settings chosen for the demo, "
            "so these results describe the demo and nothing else."
        )
    st.write(
        "Everything on this page is observed in your orders. Nothing is forecast. "
        "Money is in the currency your file uses."
    )

    saved = st.session_state.setdefault("retention_inputs", {"window": DEFAULT_WINDOW_DAYS, "cost": None, "margin": None})
    with st.expander("Your inputs", expanded=True):
        left, middle, right = st.columns(3)
        window = left.selectbox(
            "Repeat window in days", WINDOW_CHOICES, index=WINDOW_CHOICES.index(saved["window"]),
            key=f"opt_{ds['id']}_window", help="How soon after a first order a repeat order counts.",
        )
        cost = middle.number_input(
            "Cost to win one customer", min_value=0.0, value=saved["cost"], step=1.0, format="%.2f",
            placeholder="Enter your cost", key=f"opt_{ds['id']}_cost",
            help="Your ad and sales cost per new customer. Payback needs it. There is no default.",
        )
        margin = right.number_input(
            "Gross margin percent, optional", min_value=0.01, max_value=100.0, value=saved["margin"], step=1.0,
            format="%.1f", placeholder="Enter your margin", key=f"opt_{ds['id']}_margin",
            help="Share of revenue you keep after product cost. Without it, payback uses revenue.",
        )
    st.session_state["retention_inputs"] = {"window": window, "cost": cost, "margin": margin}

    try:
        with st.spinner("Calculating"):
            report = retention_report(frame, window_days=window, cost_to_win=cost, margin_pct=margin)
    except ValueError as err:
        st.error(str(err))
        return
    for warning in report.warnings:
        st.warning(warning)

    # command row
    command_row(frame, report)

    # repeat purchase
    st.markdown("**Repeat purchase**")
    rep = report.repeat
    cols = st.columns(4)
    cols[0].metric("Customers who ordered again", f"{rep['repeat_rate']:.1%}", border=True)
    cols[1].metric(
        f"Ordered again within {window} days",
        f"{rep['repeat_in_window_rate']:.1%}" if rep["repeat_in_window_rate"] is not None else "Not enough history",
        border=True,
    )
    cols[2].metric(
        "Median days to a second order",
        f"{rep['median_days_to_second']:.0f}" if rep["median_days_to_second"] is not None else "None yet",
        border=True,
    )
    cols[3].metric("Average order value", money(rep["average_order_value"]), border=True)
    st.caption(
        f"{rep['repeat_customers']:,} of {rep['customers']:,} customers placed two or more orders. "
        f"The {window} day rate counts only the {rep['eligible_customers']:,} customers whose first order is at least "
        f"{window} days before the last order in the file, so recent customers are not undercounted. "
        "The median covers only customers who did order again, so it reads low when many are still waiting."
    )

    # funnel
    st.markdown("**How far customers get**")
    steps = [
        (f"{int(r.orders)} or more orders" if r.orders > 1 else "At least 1 order", int(r.customers), float(r.share),
         None if pd.isna(r.share_of_previous) else float(r.share_of_previous))
        for r in report.funnel.itertuples()
    ]
    st.html(ui.funnel_html(steps))
    st.caption(
        "Each layer counts customers who placed at least that many orders, counted from your file and not predicted. "
        "Layer widths are scaled so small steps stay visible, so read the exact shares on the right."
    )

    # cohorts
    st.markdown("**Cohort retention**")
    cohorts = report.cohorts
    table = cohorts.retention.copy()
    table.columns = [f"Month {k}" for k in table.columns]
    table.insert(0, "Customers", cohorts.sizes)
    pooled = cohorts.average.copy()
    pooled.index = [f"Month {k}" for k in pooled.index]
    table.loc["All cohorts"] = pd.concat([pd.Series({"Customers": cohorts.sizes.sum()}), pooled])
    shares = [c for c in table.columns if c != "Customers"]
    tinted = [c for c in shares if c != "Month 0"]  # month 0 is always 100 percent, so it stays plain
    st.dataframe(
        table.style.format({"Customers": "{:,.0f}"}).format("{:.0%}", subset=shares, na_rep="")
        .map(ui.tint_style, subset=tinted),
        width="stretch",
    )
    st.caption(
        "Each row groups customers by the calendar month of their first order. Each cell is the share of that group "
        "who ordered in that month after, with month 0 as the first order month. Blank means the month has not "
        "happened yet in the file. The last row pools every cohort that has reached that month. "
        "Shading steps up at 5, 10, 20 and 40 percent, so lighter means more customers came back."
    )

    # segments
    st.markdown("**Customer segments**")
    seg = report.segments.reset_index().rename(columns={
        "segment": "Segment", "customers": "Customers", "share_of_customers": "Share of customers",
        "average_orders": "Average orders", "average_spend": "Average spend", "share_of_revenue": "Share of revenue",
    })[["Segment", "Customers", "Share of customers", "Average orders", "Average spend", "Share of revenue"]]
    st.dataframe(
        seg.style.format({
            "Customers": "{:,.0f}", "Share of customers": "{:.0%}", "Average orders": "{:.1f}",
            "Average spend": "{:,.2f}", "Share of revenue": "{:.0%}",
        }),
        hide_index=True, width="stretch",
    )
    st.caption(
        "Customers are scored 1 to 5 on how recently they bought, how often, and how much they spent, "
        "ranked within this file and counted back from the last order date in it. The scores then sort them into segments."
    )
    with st.expander("How segments are decided"):
        for name in SEGMENT_ORDER:
            st.write(f"{name}: {SEGMENT_RULES[name]}")
        st.write("Rules are checked from New down to Lapsed, and the first match wins.")

    # value and payback
    st.markdown("**Customer value and payback**")
    curve = report.curve
    chart_cols = ["revenue_per_customer"] + (["margin_per_customer"] if "margin_per_customer" in curve else [])
    st.line_chart(
        curve.set_index("month")[chart_cols].rename(columns={
            "revenue_per_customer": "Revenue per customer", "margin_per_customer": "Margin per customer",
        }),
        x_label="Months since the first order month", y_label="Cumulative value per customer",
    )
    st.caption(
        "Month 0 is the month of a customer's first order. Each point uses only customers who have had that many months "
        "to order, so later months rest on fewer and older customers and the line can dip."
    )
    with st.expander("Customers behind each month"):
        behind = curve.rename(columns={
            "month": "Month", "customers_observed": "Customers observed",
            "revenue_per_customer": "Revenue per customer", "margin_per_customer": "Margin per customer",
        })
        st.dataframe(
            behind.style.format({"Customers observed": "{:,.0f}", "Revenue per customer": "{:,.2f}", "Margin per customer": "{:,.2f}"}),
            hide_index=True, width="stretch",
        )
        st.caption("Later months rest on fewer customers, so read them with care.")
    left, right = st.columns(2)
    if report.twelve_month is not None:
        left.metric("Revenue per customer in the first 12 months", money(report.twelve_month), border=True)
    else:
        left.metric("Revenue per customer in the first 12 months", "Not enough history", border=True)
    pay = report.payback
    basis = "margin" if pay["basis"] == "margin" else "revenue"
    if not pay["entered"]:
        right.metric("Payback month", "Enter your cost", border=True)
    elif pay["reached"]:
        right.metric("Payback month", f"Month {pay['month']}", border=True)
    else:
        right.metric("Payback month", "Not reached", border=True)
    if not pay["entered"]:
        st.caption("Enter what it costs you to win one customer to see payback.")
    elif pay["reached"]:
        st.caption(
            f"Payback is the first month when cumulative {basis} per customer reaches your cost of {money(cost)}, "
            "counting the first order month as month 0."
            + (" It uses revenue because no margin was entered, so it overstates what you keep." if basis == "revenue" else "")
        )
    else:
        st.caption(
            f"Cumulative {basis} per customer has not reached {money(cost)} within the {len(curve)} months in this file."
        )
    privacy_note()


# ------------------------------------------------------------------ main

def main() -> None:
    ui.inject_css()
    st.title("Retention spend rebalancer")
    stage = st.session_state.get("stage", 1)
    if "dataset" not in st.session_state:
        stage = 1
    ui.stepper(stage)
    {1: stage_load, 2: stage_columns, 3: stage_review, 4: stage_results}[stage]()


main()
