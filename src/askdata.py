"""Ask questions of the cleaned orders with DuckDB, safely.

The AI sees only the column names and types, never any rows, and writes one SELECT query. The code
checks that query and runs it locally. The answer comes from the database, and results are never
sent back to the AI. Every query runs on a fresh in-memory connection with file access switched off,
so nothing a query does can last or reach beyond the cleaned orders.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import duckdb
import pandas as pd

from src.checker import check_text

AIFunction = Callable[[str], str]
TABLE = "orders"
MAX_SQL_CHARS = 3000
MAX_QUESTION_CHARS = 300
MAX_ROWS = 1000
TIMEOUT_SECONDS = 5.0
MEMORY_LIMIT = "512MB"

COLUMN_NOTES = {
    "customer_id": ("VARCHAR", "who placed the order"),
    "order_date": ("TIMESTAMP", "when the order was placed"),
    "order_value": ("DOUBLE", "the money value of the order"),
    "order_id": ("VARCHAR", "the order number, present only if the file had one"),
}

PRESETS = {
    "Top 10 customers by spend": (
        "SELECT customer_id, count(*) AS orders, round(sum(order_value), 2) AS total_spend FROM orders "
        "GROUP BY customer_id ORDER BY total_spend DESC, customer_id LIMIT 10"
    ),
    "Customers with the most orders": (
        "SELECT customer_id, count(*) AS orders FROM orders GROUP BY customer_id ORDER BY orders DESC, customer_id LIMIT 10"
    ),
    "Biggest single orders": (
        "SELECT customer_id, order_date, order_value FROM orders ORDER BY order_value DESC, customer_id LIMIT 10"
    ),
    "Orders and revenue by month": (
        "SELECT strftime(order_date, '%Y-%m') AS month, count(*) AS orders, round(sum(order_value), 2) AS revenue "
        "FROM orders GROUP BY 1 ORDER BY 1"
    ),
    "Average order value by month": (
        "SELECT strftime(order_date, '%Y-%m') AS month, round(avg(order_value), 2) AS average_order_value "
        "FROM orders GROUP BY 1 ORDER BY 1"
    ),
    "Repeat rate by first order month": (
        "WITH per AS (SELECT customer_id, min(order_date) AS first_order, count(*) AS orders FROM orders GROUP BY 1) "
        "SELECT strftime(first_order, '%Y-%m') AS first_month, count(*) AS customers, "
        "sum(CASE WHEN orders >= 2 THEN 1 ELSE 0 END) AS repeat_customers, "
        "round(100.0 * sum(CASE WHEN orders >= 2 THEN 1 ELSE 0 END) / count(*), 1) AS repeat_percent "
        "FROM per GROUP BY 1 ORDER BY 1"
    ),
}

# Functions that read files, settings or the environment. Table functions are refused separately.
_DENIED_FUNCTIONS = re.compile(
    r"^(read_\w+|duckdb_\w+|pragma_\w+|parquet_\w+|glob|getenv|current_setting|sniff_csv|query|query_table|"
    r"json_serialize_sql|json_deserialize_sql|which_secret|current_database|current_schema|current_catalog)$"
)


class AskError(Exception):
    """A problem the user can read. The message never repeats raw model output or system details."""


# ----------------------------------------------------------------------- guard

def guard_sql(sql: object) -> str:
    """Return the query without a trailing semicolon, or raise AskError. Only one SELECT is allowed."""
    if not isinstance(sql, str) or not sql.strip():
        raise AskError("There was no query to run.")
    text = sql.strip().rstrip(";").strip()
    if len(text) > MAX_SQL_CHARS:
        raise AskError("The query is too long to run.")
    try:
        statements = duckdb.extract_statements(text)
    except Exception:
        raise AskError("The query could not be read as SQL.") from None
    if len(statements) != 1:
        raise AskError("Only one query can run at a time.")
    if statements[0].type != duckdb.StatementType.SELECT or _first_word(text) not in ("select", "with", "from", "("):
        raise AskError("Only SELECT queries are allowed. Nothing can be changed.")
    return text


_LEADING_COMMENT = re.compile(r"^\s*(--[^\n]*(\n|$)|/\*.*?\*/)", re.DOTALL)


def _first_word(text: str) -> str:
    """The first real word of a query, after any leading comments. DuckDB treats DESCRIBE, SHOW and SUMMARIZE as
    selects, so the statement type alone is not enough."""
    rest = text
    while True:
        match = _LEADING_COMMENT.match(rest)
        if not match:
            break
        rest = rest[match.end():]
    word = re.match(r"\s*(\(|[A-Za-z_]+)", rest)
    return word.group(1).lower() if word else ""


def _walk(node, found: dict) -> None:
    """Collect tables, table functions, functions and CTE names from DuckDB's parsed form of the query."""
    if isinstance(node, dict):
        kind = node.get("type")
        if kind == "BASE_TABLE":
            found["tables"].append((node.get("catalog_name") or "", node.get("schema_name") or "", str(node.get("table_name") or "")))
        elif kind == "TABLE_FUNCTION":
            found["table_functions"].append(str((node.get("function") or {}).get("function_name") or "?"))
        if node.get("class") == "FUNCTION":
            found["functions"].append(str(node.get("function_name") or ""))
        for entry in (node.get("cte_map") or {}).get("map", []):
            found["ctes"].add(str(entry.get("key", "")).lower())
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)


def inspect_query(con: duckdb.DuckDBPyConnection, text: str) -> None:
    """Refuse a query that touches anything but the orders table or that calls a file or setting function.

    This reads DuckDB's own parse of the query, so it cannot be fooled by comments, quoting or spacing.
    """
    try:
        tree = json.loads(con.execute("SELECT json_serialize_sql(?)", [text]).fetchone()[0])
    except Exception:
        raise AskError("The query could not be checked, so it was not run.") from None
    if tree.get("error"):
        raise AskError("The query could not be read as SQL.")
    found = {"tables": [], "table_functions": [], "functions": [], "ctes": set()}
    _walk(tree, found)
    if found["table_functions"]:
        raise AskError("Table functions are not allowed. Only the orders table can be queried.")
    for catalog, schema, name in found["tables"]:
        if catalog or schema not in ("", "main") or (name.lower() != TABLE and name.lower() not in found["ctes"]):
            raise AskError("Only the orders table can be queried.")
    if any(_DENIED_FUNCTIONS.match(fn.lower()) for fn in found["functions"]):
        raise AskError("That query calls a function that reads files or settings, which is not allowed.")


def _connect(frame: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    """A fresh in-memory connection with file and extension access off and the orders as a view."""
    con = duckdb.connect(":memory:", config={
        "enable_external_access": False, "autoinstall_known_extensions": False, "autoload_known_extensions": False,
        "memory_limit": MEMORY_LIMIT, "threads": 2,
    })
    con.register(TABLE, frame)
    con.execute("SET lock_configuration = true")
    return con


@dataclass
class QueryResult:
    table: pd.DataFrame
    sql: str
    truncated: bool
    seconds: float


def run_query(frame: pd.DataFrame, sql: str, guard: bool = True, max_rows: int = MAX_ROWS,
              timeout: float = TIMEOUT_SECONDS) -> QueryResult:
    """Check and run one query on a throwaway connection. guard=False exists only so tests can prove the
    sandbox holds even if the check were bypassed."""
    text = guard_sql(sql) if guard else sql
    con = _connect(frame)
    timer = threading.Timer(timeout, con.interrupt)
    started = time.monotonic()
    try:
        if guard:
            inspect_query(con, text)
        timer.start()
        cursor = con.execute(text)
        rows = cursor.fetchmany(max_rows + 1)
        columns = [d[0] for d in cursor.description]
    except AskError:
        raise
    except duckdb.InterruptException:
        raise AskError("The query took too long and was stopped.") from None
    except duckdb.PermissionException:
        raise AskError("That query tried to reach something outside the orders table, so it was stopped.") from None
    except duckdb.Error as err:
        raise AskError("The query did not run: " + str(err).splitlines()[0][:160]) from None
    finally:
        timer.cancel()
        con.close()
    return QueryResult(pd.DataFrame(rows[:max_rows], columns=columns), text, len(rows) > max_rows, time.monotonic() - started)


def run_preset(frame: pd.DataFrame, name: str) -> QueryResult:
    if name not in PRESETS:
        raise AskError("That is not one of the ready-made questions.")
    return run_query(frame, PRESETS[name])


# ------------------------------------------------------------------ AI to SQL

def schema_text(frame: pd.DataFrame) -> str:
    """The table layout the model may see: names and types only, no values."""
    lines = [f"Table {TABLE}, one row per order:"]
    for column in frame.columns:
        kind, note = COLUMN_NOTES.get(column, ("VARCHAR", "a column of the cleaned orders"))
        lines.append(f"- {column} ({kind}): {note}")
    return "\n".join(lines)


def sql_prompt(question: str, frame: pd.DataFrame) -> str:
    return (
        "You write one DuckDB SQL query that answers a question about an online store's orders.\n"
        "Rules:\n"
        f"- Use only the table {TABLE} and its columns below. Do not use any other table.\n"
        "- Write exactly one SELECT query. No other statements, no comments, no semicolons inside the query.\n"
        "- Do not use table functions such as read_csv or range. Use plain tables, joins, CTEs and aggregate functions.\n"
        "- Round money to 2 decimals with round(x, 2). Use strftime(order_date, '%Y-%m') for months.\n"
        "- Limit lists to at most 50 rows.\n"
        'Reply with JSON only: {"title": "a short plain title with no numbers", "sql": "the query"}\n\n'
        f"{schema_text(frame)}\n\nQuestion: {question}"
    )


def parse_sql_reply(reply: object) -> Optional[dict]:
    """Strict parse. None on anything unexpected."""
    if not isinstance(reply, str):
        return None
    body = reply.strip()
    fenced = re.fullmatch(r"```(?:\w+)?\s*(.*?)\s*```", body, flags=re.S)
    if fenced:
        body = fenced.group(1)
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sql"), str) or not data["sql"].strip():
        return None
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        return None
    return {"sql": data["sql"], "title": (title or "").strip()[:80]}


@dataclass
class Answer:
    title: str
    result: QueryResult


def ask(frame: pd.DataFrame, question: str, ai_fn: Optional[AIFunction]) -> Answer:
    """Turn a question into a checked query and run it. The result is never sent back to the AI."""
    question = (question or "").strip()
    if not question:
        raise AskError("Type a question first.")
    if len(question) > MAX_QUESTION_CHARS:
        raise AskError(f"Keep the question under {MAX_QUESTION_CHARS} characters.")
    if ai_fn is None:
        raise AskError("AI is off. Pick one of the ready-made questions, or turn AI on.")
    try:
        reply = ai_fn(sql_prompt(question, frame))
    except Exception as err:
        from src.insights import friendly_error

        raise AskError(friendly_error(err)) from None
    parsed = parse_sql_reply(reply)
    if parsed is None:
        raise AskError("The AI reply was not in the expected format. Try rewording the question.")
    title = parsed["title"] if parsed["title"] and check_text(parsed["title"], {}).ok else "Your question"
    return Answer(title, run_query(frame, parsed["sql"]))
