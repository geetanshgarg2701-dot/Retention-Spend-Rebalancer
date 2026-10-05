"""Retention spend rebalancer: load an order export, confirm columns, review cleaning, see retention results."""
from __future__ import annotations

import dataclasses
import logging
import os

import pandas as pd
import streamlit as st

from src import ui
from src.cleaning import clean_orders, steps_to_frame
from src.loading import MAX_ROWS, MAX_UPLOAD_MB, LoadError, read_upload
from src.mapper import FIELD_HELP, FIELD_LABELS, FIELDS, REQUIRED_FIELDS, gemini_ai_function, map_columns
from src.metrics import (
    DEFAULT_WINDOW_DAYS, SEGMENT_ORDER, SEGMENT_RULES, WINDOW_CHOICES, monthly_orders, payback_progress, retention_report,
)
from src import aiconfig, askdata
from src import insights as ins
from src import scenario as sc
from src.quantity import QUANTITY_CHOICES, quantity_preview
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
SESSION_PREFIXES = ("map_", "mapres_", "opt_", "ins_")
SESSION_KEYS = (
    "dataset", "stage", "confirmed", "clean", "load_error", "upload_id", "retention_inputs", "scenario_inputs",
    "scenario_result", "ai_budget", "clean_n",
)

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


def _digest(value) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def session_cached(name: str, parts: tuple, compute):
    """Keep the latest result of a heavy calculation for this session, keyed by what it depends on.

    Widget clicks rerun the whole page, so without this a big file would be recalculated on every click.
    One result is kept per name, so memory stays bounded. The keys start with ins_, so a new file clears them.
    """
    slot = f"ins_cache_{name}"
    digest = _digest(list(parts))
    held = st.session_state.get(slot)
    if held and held[0] == digest:
        return held[1]
    value = compute()
    st.session_state[slot] = (digest, value)
    return value


def clean_version() -> int:
    """Changes every time the orders are cleaned again, so cached results for old data are never reused."""
    return int(st.session_state.get("clean_n", 0))


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
        nodes=ui.STEPS,
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
        "Privacy: your file is processed in this session and is not stored. On a hosted server it is held in the "
        "server's memory for the session only, and the app does not write it to disk or a database. "
        "If AI matching is on, only column names and up to three masked sample values per column "
        "go to the Gemini API, with emails and phone-like numbers replaced by placeholders. "
        "Columns that look personal, such as names, phones and addresses, send the column name only. "
        "Order rows and customer data are never sent. "
        "On the free Gemini tier, Google may use what is sent to improve its products, "
        "and people may review it. If you use the AI features on the insights screen, only the calculated figures shown "
        "there go to Gemini, plus the column names and your own question if you ask one. Query results never go back "
        "to the model. You can turn AI off at any time."
    )


# ------------------------------------------------------------------ stage 2

def get_mapping(ds: dict, use_ai: bool):
    key = f"mapres_{ds['id']}_{use_ai}"
    if key not in st.session_state:
        raw_ai = gemini_ai_function() if use_ai else None
        ai_fn = ins.with_daily(raw_ai) if raw_ai is not None else None  # column matching counts against the shared daily cap
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

    ai_available = aiconfig.ai_available()
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
        if "quantity" in chosen and "order_value" in chosen:
            multiply = _quantity_choice(raw, chosen, confirmed, ds, use_ai)
            if multiply is None:
                problems.append("Say whether the order value is the total for the whole order or the price of one item.")
        else:
            multiply = False
            st.caption("Quantity is not used, because no quantity column is picked.")

    for problem in problems:
        st.error(problem)
    if st.button("Confirm columns and clean", key="confirm_columns", disabled=bool(problems), type="primary"):
        options = {
            "mapping": chosen, "dayfirst": DATE_CHOICES[date_label],
            "line_item_mode": LINE_CHOICES[line_label], "multiply_quantity": bool(multiply),
        }
        try:
            with st.spinner(f"Cleaning {len(raw):,} rows"):
                outcome = clean_orders(
                    raw, chosen, dayfirst=options["dayfirst"],
                    line_item_mode=options["line_item_mode"], multiply_quantity=options["multiply_quantity"],
                )
        except ValueError as err:
            st.error(str(err))
            return
        st.session_state["confirmed"] = options
        st.session_state["clean"] = outcome
        st.session_state["clean_n"] = clean_version() + 1
        st.session_state["stage"] = 3
        st.rerun()
    privacy_note()


def _index_of(choices: dict, value) -> int:
    return list(choices.values()).index(value)


def _quantity_choice(raw, chosen: dict, confirmed, ds: dict, use_ai: bool):
    """Ask how to read the order value when a quantity column is picked. Nothing is pre-selected on a first visit."""
    st.markdown("**How should the order value be read?**")
    preview = quantity_preview(raw, chosen["order_value"], chosen["quantity"])
    if preview is not None:
        st.caption(
            f'The first rows of "{chosen["order_value"]}" and "{chosen["quantity"]}" in your file, '
            "with the line value under each reading."
        )
        st.table(preview.examples.style.format("{:,.2f}"))
        st.caption(
            f"Average line value across {preview.rows_used:,} rows: "
            f"{preview.average_if_total:,.2f} if the order value is a total, "
            f"{preview.average_if_unit:,.2f} if it is the price of one item. "
            "Pick the reading that matches what one order looks like in your store."
        )
    labels = list(QUANTITY_CHOICES)
    pick = st.radio(
        "Order value meaning", labels, index=_index_of(QUANTITY_CHOICES, confirmed["multiply_quantity"]) if confirmed else None,
        key=f"opt_{ds['id']}_multiply_{use_ai}", label_visibility="collapsed",
    )
    return None if pick is None else QUANTITY_CHOICES[pick]


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
        # The file is built only when the button is clicked, so a big file is not rebuilt on every page rerun.
        st.download_button(
            "Download clean CSV",
            lambda: frame.to_csv(index=False, float_format="%.2f", date_format="%Y-%m-%d %H:%M:%S").encode("utf-8"),
            file_name="synthetic_clean_orders.csv" if ds["synthetic"] else "clean_orders.csv",
            mime="text/csv", key="download_clean", on_click="ignore",
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
    monthly = session_cached(
        "monthly", (st.session_state["dataset"]["id"], clean_version()), lambda: monthly_orders(frame)
    )
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
            report = session_cached(
                "report", (ds["id"], clean_version(), window, cost, margin),
                lambda: retention_report(frame, window_days=window, cost_to_win=cost, margin_pct=margin),
            )
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
    if st.button("Continue to the budget scenario", key="to_scenario", type="primary"):
        st.session_state["stage"] = 5
        st.rerun()
    privacy_note()


# ------------------------------------------------------------------ stage 5

def scenario_chart(sim, selected_pct: int) -> None:
    import altair as alt

    pal = ui.PALETTE
    df = pd.DataFrame({
        "Shift": (sim.shifts * 100).round().astype(int), "Low": sim.p10, "Middle": sim.median, "High": sim.p90,
    })
    x = alt.X("Shift:Q", title="Share of the budget moved toward retention, percent")
    tip = [alt.Tooltip("Shift:Q", title="Shift, percent"), alt.Tooltip("Low:Q", title="Low", format=",.0f"),
           alt.Tooltip("Middle:Q", title="Middle", format=",.0f"), alt.Tooltip("High:Q", title="High", format=",.0f")]
    band = alt.Chart(df).mark_area(opacity=0.25, color=pal["teal"]).encode(
        x=x, y=alt.Y("Low:Q", title="Estimated change in value"), y2=alt.Y2("High:Q"))
    line = alt.Chart(df).mark_line(color=pal["teal"], strokeWidth=2.5).encode(x=x, y="Middle:Q", tooltip=tip)
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=pal["muted"], strokeDash=[4, 4]).encode(y="y:Q")
    chosen = alt.Chart(pd.DataFrame({"Shift": [selected_pct]})).mark_rule(color=pal["amber"], strokeWidth=2).encode(x="Shift:Q")
    chart = (
        (band + line + zero + chosen).properties(height=300)
        .configure(background="transparent")
        .configure_axis(labelColor=pal["muted"], titleColor=pal["muted"], gridColor=pal["line"],
                        domainColor=pal["edge"], tickColor=pal["edge"])
        .configure_view(stroke=None)
    )
    st.altair_chart(chart, theme=None, width="stretch")


def stage_scenario() -> None:
    ds = st.session_state["dataset"]
    frame = st.session_state["clean"].frame
    retention = st.session_state.get("retention_inputs") or {"cost": None, "margin": None}
    st.subheader("Budget scenario")
    if st.button("Back to the retention results", key="back_to_results"):
        st.session_state["stage"] = 4
        st.rerun()
    if ds["synthetic"]:
        st.info(
            SYNTHETIC_NOTICE + " The numbers you enter below are yours to choose, and the results describe the demo only."
        )
    st.html(ui.tags_html(["Estimate", "Not a forecast", "Rests on your assumptions"]))
    st.write(
        "See what could change if some budget moves from winning new customers to keeping the ones you have. "
        "Customer value comes from your orders. The costs are your own figures, because orders cannot show "
        "what retention spend achieves."
    )

    default_exponent, default_uncertainty = sc.DEFAULT_EXPONENT, int(sc.DEFAULT_UNCERTAINTY * 100)
    saved = st.session_state.setdefault("scenario_inputs", {
        "horizon": 12, "budget": None, "share": None, "cost_win": retention["cost"], "cost_back": None,
        "exponent": default_exponent, "uncertainty": default_uncertainty, "extra_orders": None,
    })
    key = f"opt_{ds['id']}_s_"
    with st.expander("Your inputs", expanded=True):
        a, b, c = st.columns(3)
        horizon = a.selectbox("Horizon in months", sc.HORIZON_CHOICES, index=sc.HORIZON_CHOICES.index(saved["horizon"]),
                              key=key + "horizon", help="How far ahead the estimate looks.")
        budget = b.number_input(f"Marketing budget over {horizon} months", min_value=0.0, value=saved["budget"], step=100.0,
                                format="%.2f", placeholder="Enter your budget", key=key + "budget",
                                help="Everything you plan to spend on winning and keeping customers over the horizon.")
        share = c.number_input("Share spent on winning new customers today, percent", min_value=0.0, max_value=100.0,
                               value=saved["share"], step=5.0, format="%.1f", placeholder="Enter a percent",
                               key=key + "share", help="The rest is treated as spent on keeping customers.")
        d, e = st.columns(2)
        cost_win = d.number_input("Cost to win one customer", min_value=0.0, value=saved["cost_win"], step=1.0, format="%.2f",
                                  placeholder="Enter your cost", key=key + "cost_win")
        cost_back = e.number_input("Cost to bring one customer back", min_value=0.0, value=saved["cost_back"], step=1.0,
                                   format="%.2f", placeholder="Enter your cost", key=key + "cost_back",
                                   help="What it costs you to win back one customer who would not have ordered again. "
                                        "Orders cannot measure this, so it is your estimate. The ranges below let you say how unsure you are.")

    observed = session_cached(
        "observed", (ds["id"], clean_version(), horizon, retention.get("margin")),
        lambda: sc.observed_inputs(frame, horizon, retention.get("margin")),
    )
    with st.expander("Advanced assumptions", expanded=False):
        f, g, h = st.columns(3)
        exponent = f.number_input("Diminishing returns exponent", min_value=sc.MIN_EXPONENT, max_value=1.0,
                                  value=float(saved["exponent"]), step=0.05, format="%.2f", key=key + "exponent",
                                  help="Below 1, doubling spend gives less than double the customers. 1 means no diminishing "
                                       "returns. The default is an illustrative assumption, not a measurement.")
        uncertainty = g.number_input("Uncertainty, plus or minus percent", min_value=0, max_value=90,
                                     value=int(saved["uncertainty"]), step=5, key=key + "uncertainty",
                                     help="How far the costs, extra orders and exponent may be from what you entered.")
        extra = h.number_input("Extra orders from a brought-back customer", min_value=0.0, value=saved["extra_orders"],
                               step=0.1, format="%.2f", placeholder=f"Observed {observed['extra_orders']:.2f}",
                               key=key + "extra", help="Leave empty to use the average extra orders your repeat customers placed. Those customers "
                                      "came back on their own, so this may be generous for customers you pay to bring back.")
        st.caption(
            f"From your orders, in {observed['basis']}: a new customer is worth {money(observed['value_new'])} by month "
            f"{observed['value_new_month'] + 1}, one order averages {money(observed['order_value'])}, and "
            f"{observed['repeat_customers']:,} repeat customers placed {observed['extra_orders']:.2f} extra orders on average."
        )
    st.session_state["scenario_inputs"] = {
        "horizon": horizon, "budget": budget, "share": share, "cost_win": cost_win, "cost_back": cost_back,
        "exponent": exponent, "uncertainty": uncertainty, "extra_orders": extra,
    }

    missing = [name for name, value in (
        ("the budget", budget), ("today's share on winning customers", share),
        ("the cost to win a customer", cost_win), ("the cost to bring a customer back", cost_back),
    ) if value is None]
    if missing:
        st.info("Enter " + ", ".join(missing) + " to see the scenario.")
        privacy_note()
        return
    if observed["history_short"]:
        st.warning(
            f"Your orders cover fewer than {horizon} months, so a new customer's value is taken at month "
            f"{observed['value_new_month'] + 1}. A longer horizon is probably understated."
        )
    if observed["repeat_customers"] == 0 and extra is None:
        st.warning("No customer ordered more than once, so brought-back customers are worth nothing unless you enter extra orders.")

    inputs = sc.Inputs(
        budget=budget, acquisition_share=share / 100, cost_to_win=cost_win, cost_to_bring_back=cost_back,
        value_new=observed["value_new"], extra_orders=extra if extra is not None else observed["extra_orders"],
        order_value=observed["order_value"], exponent=exponent,
    )
    try:
        with st.spinner("Simulating"):
            ranges = sc.ranges_from_pct(inputs, uncertainty / 100)
            sim = session_cached("sim", (dataclasses.astuple(inputs), uncertainty), lambda: sc.simulate(inputs, ranges))
    except ValueError as err:
        st.error(str(err))
        return

    low, high = sc.allowed_shift_pct(inputs.acquisition_share)
    best = max(low, min(high, round(sim.best_median * 100)))
    if low == high:
        st.info("This split leaves no room to move money.")
        shift = 0
    else:
        shift = st.slider(
            "Move this share of the budget toward retention, in percent", low, high, best, format="%d",
            key=f"{key}shift_{low}_{high}_{best}",
            help="Percent of your total budget. Positive moves money to keeping customers, negative moves it to winning them. "
                 "It starts at the best move found in the simulations.",
        )
    idx = int(shift - low)
    before, after = sc.evaluate(inputs, 0.0), sc.evaluate(inputs, shift / 100)
    st.session_state["scenario_result"] = ins.scenario_facts(inputs, sim, int(shift), horizon, observed["basis"])

    cols = st.columns(4)
    cols[0].metric(
        "Estimated change in value", f"{sim.median[idx]:+,.0f}", border=True,
        help=f"Middle estimate in {observed['basis']} over {horizon} months. Range {sim.p10[idx]:,.0f} to {sim.p90[idx]:,.0f}.",
    )
    cols[1].metric("Chance it beats today's split", f"{sim.prob_positive[idx]:.0%}", border=True,
                   help=f"Share of {sim.draws:,} simulations where this move gains value.")
    cols[2].metric("New customers won", f"{after['new_customers']:,.0f}", border=True,
                   delta=f"{after['new_customers'] - before['new_customers']:+,.0f}")
    cols[3].metric("Customers brought back", f"{after['brought_back']:,.0f}", border=True,
                   delta=f"{after['brought_back'] - before['brought_back']:+,.0f}")
    st.caption(
        f"Range for the change in value: {sim.p10[idx]:,.0f} to {sim.p90[idx]:,.0f} in {observed['basis']}. "
        "The customer figures compare your chosen split with today's split, using the middle assumptions."
    )
    st.write(sc.summarize(inputs, sim, int(shift), horizon, observed["basis"]))

    st.markdown("**Change in value for every possible move**")
    scenario_chart(sim, int(shift))
    st.caption(
        "The teal line is the middle estimate and the shaded band runs from the low to the high estimate. "
        "The amber line marks your chosen move and the dashed line is no change. Everything above the dashed line gains value."
    )

    st.markdown("**Assumptions behind these estimates**")
    entered = {"budget", "acquisition_share", "cost_to_win", "cost_to_bring_back"}
    if exponent != default_exponent:
        entered.add("exponent")
    if extra is not None:
        entered.add("extra_orders")
    if uncertainty != default_uncertainty:
        entered.add("ranges")
    st.dataframe(sc.assumptions_table(inputs, ranges, observed, horizon, entered), hide_index=True, width="stretch")
    with st.expander("What this cannot tell you", expanded=True):
        for line in sc.CAVEATS:
            st.write(line)
    if st.button("Continue to insights", key="to_insights", type="primary"):
        st.session_state["stage"] = 6
        st.rerun()
    privacy_note()


# ------------------------------------------------------------------ stage 6

def _ai_functions(use_ai: bool, budget):
    """Text and JSON model calls that share one call budget, or None for both when AI is off."""
    if not use_ai:
        return None, None
    text_fn, json_fn = gemini_ai_function(json_mode=False), gemini_ai_function(json_mode=True)
    if text_fn is None or json_fn is None:
        return None, None
    return ins.with_budget(text_fn, budget), ins.with_budget(json_fn, budget)


def stage_insights() -> None:
    import json

    ds = st.session_state["dataset"]
    frame = st.session_state["clean"].frame
    retention = st.session_state.get("retention_inputs") or {"window": DEFAULT_WINDOW_DAYS, "cost": None, "margin": None}
    st.subheader("Insights")
    if st.button("Back to the budget scenario", key="back_to_scenario"):
        st.session_state["stage"] = 5
        st.rerun()
    if ds["synthetic"]:
        st.info(SYNTHETIC_NOTICE)
    st.html(ui.tags_html(["Code does the numbers", "AI helps with the words", "Every figure is checked"]))
    st.write(
        "A plain summary, ideas for each customer group, and a way to ask your own questions. "
        "The AI never calculates anything. Each figure it writes must match one the app already calculated, "
        "or the text is thrown away and the app's own text is shown."
    )

    ai_ok = aiconfig.ai_available()
    use_ai = st.toggle("Use AI for these features", value=ai_ok, disabled=not ai_ok, key="insights_ai",
                       help="Sends only the figures shown under Exactly what is sent, and your own question if you ask one.")
    if not ai_ok:
        st.caption("AI is off because no Gemini key is set. The app's own summary, ideas and ready-made questions still work.")
    budget = st.session_state.setdefault("ai_budget", ins.CallBudget())
    if ai_ok and use_ai:
        st.caption(f"AI calls used this session: {budget.used} of {budget.limit}. The free Gemini tier is shared, so the app caps each session.")
    text_fn, json_fn = _ai_functions(use_ai, budget)
    day_left = ins.GLOBAL_DAILY.left
    if ai_ok and use_ai and day_left == 0:
        st.caption("The shared AI limit for today has been reached, so AI is paused until tomorrow. The app's own text still works.")
        text_fn = json_fn = None
    can_call = text_fn is not None and budget.left > 0

    report = session_cached(
        "report", (ds["id"], clean_version(), retention["window"], retention["cost"], retention["margin"]),
        lambda: retention_report(frame, window_days=retention["window"], cost_to_win=retention["cost"], margin_pct=retention["margin"]),
    )
    monthly = session_cached("monthly", (ds["id"], clean_version()), lambda: monthly_orders(frame))
    facts = ins.build_facts(report, monthly, retention["window"], retention["cost"], st.session_state.get("scenario_result"))
    key = _digest(facts)
    summary_tab, ideas_tab, ask_tab = st.tabs(["Summary", "Segment ideas", "Ask your data"])

    with summary_tab:
        cached = st.session_state.get(f"ins_summary_{key}")
        result = cached or ins.TextResult(ins.template_summary(facts), "app", "Written by the app from your results.")
        st.write(result.text)
        st.caption(result.note)
        if st.button("Write an AI summary", key="gen_summary", disabled=not can_call):
            with st.spinner("Writing"):
                st.session_state[f"ins_summary_{key}"] = ins.generate_summary(facts, text_fn)
            st.rerun()
        with st.expander("Exactly what is sent to the AI"):
            st.write("Only these calculated figures. No customer id, email, order row or order value from your file.")
            st.code(json.dumps(facts, indent=2, sort_keys=True), language="json")

    with ideas_tab:
        segs = ins.segment_facts(report)
        seg_key = _digest(segs)
        asked = st.session_state.get(f"ins_ideas_{seg_key}")
        cached_ideas = asked or ins.template_ideas()
        if asked is None and can_call:
            st.caption("These are the app's own starting ideas. Choose Get AI ideas for ideas written by AI.")
        else:
            st.caption(cached_ideas.note)
        for name in SEGMENT_ORDER:
            st.markdown(f"**{name}**, customers who {ins.SEGMENT_DESCRIPTIONS[name]}")
            for idea in cached_ideas.ideas[name]:
                st.write(f"- {idea}")
        st.caption("These are ideas to test, not predictions.")
        if st.button("Get AI ideas", key="gen_ideas", disabled=not (json_fn is not None and budget.left > 0)):
            with st.spinner("Thinking"):
                st.session_state[f"ins_ideas_{seg_key}"] = ins.generate_ideas(segs, json_fn)
            st.rerun()

    with ask_tab:
        st.write("Pick a ready-made question, which needs no AI, or type your own.")
        preset = st.selectbox("Ready-made questions", list(askdata.PRESETS), key="ins_preset")
        if st.button("Run the ready-made question", key="run_preset"):
            try:
                result = askdata.run_preset(frame, preset)
                st.session_state["ins_ask"] = {"title": preset, "result": result, "error": None}
            except askdata.AskError as err:
                st.session_state["ins_ask"] = {"title": preset, "result": None, "error": str(err)}
        question = st.text_input("Or ask your own question", max_chars=askdata.MAX_QUESTION_CHARS, key="ins_question",
                                 placeholder="For example: which month had the most orders?", disabled=json_fn is None)
        st.caption(
            "Your question and the column names go to Gemini. No order data does, and the answer is never sent back. "
            "Do not type customer names or emails."
        )
        if st.button("Ask with AI", key="run_ask", disabled=not (json_fn is not None and budget.left > 0)):
            try:
                answer = askdata.ask(frame, question, json_fn)
                st.session_state["ins_ask"] = {"title": answer.title, "result": answer.result, "error": None}
            except askdata.AskError as err:
                st.session_state["ins_ask"] = {"title": "Your question", "result": None, "error": str(err)}
        shown = st.session_state.get("ins_ask")
        if shown:
            if shown["error"]:
                st.error(shown["error"])
            else:
                st.markdown(f"**{shown['title']}**")
                st.dataframe(shown["result"].table, hide_index=True, width="stretch")
                note = f"{len(shown['result'].table):,} rows from your cleaned orders, computed by the database."
                if shown["result"].truncated:
                    note += f" Only the first {askdata.MAX_ROWS:,} rows are shown."
                st.caption(note)
                with st.expander("The query that ran"):
                    st.code(shown["result"].sql, language="sql")
    privacy_note()


# ------------------------------------------------------------------ main

def main() -> None:
    ui.inject_css()
    st.title("Retention spend rebalancer")
    stage = st.session_state.get("stage", 1)
    if "dataset" not in st.session_state:
        stage = 1
    ui.stepper(stage)
    screens = {1: stage_load, 2: stage_columns, 3: stage_review, 4: stage_results, 5: stage_scenario, 6: stage_insights}
    try:
        screens[stage]()
    except Exception as err:  # Streamlit's rerun and stop signals are not Exceptions, so they pass through
        if os.environ.get("RSR_RAISE_ERRORS") == "1":
            raise  # tests and local debugging see the real error
        # Log the kind of error and the screen only. The message can contain values from the user's file.
        logging.getLogger("rsr").error("Unhandled %s on screen %s", type(err).__name__, stage)
        st.error(
            "Something went wrong while showing this screen. Reload the page and try again. "
            "If it keeps happening, start over with a new file, or try a smaller file."
        )
        if st.button("Start over", key="error_reset"):
            reset_state()
            st.rerun()


main()
