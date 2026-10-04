"""Ask-your-data tests, with the attacks first.

The hand frame is the same ten orders used for the retention metrics:
  A 2024-01-10 100, 2024-02-20 50, 2024-04-05 50     B 2024-01-25 40, 2024-01-30 60
  C 2024-02-05 80                                    D 2024-02-15 30, 2024-05-20 70
  E 2024-05-10 90, 2024-06-15 10                     Total 580, by customer A 200, B 100, C 80, D 100, E 100
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from src import askdata as ad

ROWS = [
    ("A", "2024-01-10", 100), ("A", "2024-02-20", 50), ("A", "2024-04-05", 50),
    ("B", "2024-01-25", 40), ("B", "2024-01-30", 60),
    ("C", "2024-02-05", 80),
    ("D", "2024-02-15", 30), ("D", "2024-05-20", 70),
    ("E", "2024-05-10", 90), ("E", "2024-06-15", 10),
]


@pytest.fixture
def frame():
    df = pd.DataFrame(ROWS, columns=["customer_id", "order_date", "order_value"])
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def run(frame, sql, **kw):
    return ad.run_query(frame, sql, **kw)


# ------------------------------------------------------------------ the attacks

ATTACKS = [
    "DROP TABLE orders", "DROP VIEW orders", "DELETE FROM orders", "UPDATE orders SET order_value = 0",
    "INSERT INTO orders VALUES ('z', now(), 1)", "CREATE TABLE t AS SELECT * FROM orders", "ALTER TABLE orders ADD COLUMN x INT",
    "TRUNCATE orders", "COPY orders TO 'C:/Users/Public/out.csv'", "EXPORT DATABASE 'C:/Users/Public/x'",
    "IMPORT DATABASE 'C:/Users/Public/x'", "ATTACH 'C:/Users/Public/x.db'", "DETACH db", "INSTALL httpfs", "LOAD httpfs",
    "PRAGMA database_list", "SET enable_external_access = true", "SET lock_configuration = false", "RESET memory_limit",
    "CALL pragma_version()", "EXPLAIN SELECT * FROM orders", "ANALYZE", "VACUUM", "CHECKPOINT", "DESCRIBE orders",
    "SHOW TABLES", "SUMMARIZE orders", "USE memory", "BEGIN TRANSACTION", "COMMIT", "PREPARE p AS SELECT 1", "EXECUTE p",
]


@pytest.mark.parametrize("sql", ATTACKS)
def test_every_non_select_statement_is_refused(frame, sql):
    with pytest.raises(ad.AskError):
        run(frame, sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE orders",
    "SELECT 1 /* hi */; DROP TABLE orders",
    "SELECT * FROM orders; SELECT * FROM orders",
    "SELECT 1;\nDROP TABLE orders;",
    "SELECT 1; -- harmless\nDELETE FROM orders",
])
def test_stacked_statements_are_refused(frame, sql):
    with pytest.raises(ad.AskError, match="Only one query"):
        run(frame, sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('C:/Windows/win.ini')",
    "SELECT * FROM read_parquet('x.parquet')",
    "SELECT * FROM read_json_auto('x.json')",
    "SELECT * FROM glob('C:/*')",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM duckdb_tables()",
    "SELECT * FROM pragma_database_list()",
    "SELECT current_setting('enable_external_access')",
    "SELECT * FROM range(100)",
    "SELECT * FROM orders, generate_series(1, 10)",
    "SELECT * FROM orders o JOIN unnest([1, 2]) u ON true",
])
def test_file_settings_and_table_functions_are_refused(frame, sql):
    with pytest.raises(ad.AskError):
        run(frame, sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM 'C:/Windows/win.ini'",
    "SELECT * FROM other_table",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM orders UNION ALL SELECT * FROM secrets",
    "WITH t AS (SELECT * FROM hidden) SELECT * FROM t",
    "SELECT * FROM main.orders2",
])
def test_any_table_other_than_orders_is_refused(frame, sql):
    with pytest.raises(ad.AskError):
        run(frame, sql)


@pytest.mark.parametrize("value", [None, "", "   ", ";", 42, ["SELECT 1"]])
def test_empty_or_odd_input_is_refused(frame, value):
    with pytest.raises(ad.AskError):
        ad.guard_sql(value)


@pytest.mark.parametrize("sql", [
    "-- a comment first\nDESCRIBE orders", "/* c */ SHOW TABLES", "  \n SUMMARIZE orders", "-- x\n-- y\nPRAGMA database_list",
])
def test_leading_comments_cannot_hide_a_non_select_start(frame, sql):
    with pytest.raises(ad.AskError):
        run(frame, sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1 AS n", "select 1 as n", "  WITH t AS (SELECT 1 AS n) SELECT n FROM t", "-- note\nSELECT 1 AS n",
    "/* note */ SELECT 1 AS n", "(SELECT 1 AS n)", "FROM orders SELECT count(*) AS n",
])
def test_ordinary_queries_with_comments_or_parentheses_still_run(frame, sql):
    assert len(run(frame, sql).table) == 1


def test_an_overlong_query_is_refused(frame):
    with pytest.raises(ad.AskError, match="too long"):
        run(frame, "SELECT " + "1 + " * 2000 + "1")


def test_comments_cannot_hide_a_second_statement_or_a_blocked_word(frame):
    with pytest.raises(ad.AskError):
        run(frame, "SELECT 1 -- ; \n; DROP TABLE orders")
    with pytest.raises(ad.AskError):
        run(frame, "SELECT /* x */ * FROM read_csv('a.csv')")


def test_refusals_never_echo_the_attack_text(frame):
    with pytest.raises(ad.AskError) as caught:
        run(frame, "DROP TABLE orders; -- secret-marker-123")
    assert "secret-marker-123" not in str(caught.value)


# --------------------------------------------- the sandbox holds even without the guard

def test_file_access_is_off_even_if_the_guard_were_bypassed(frame):
    target = Path(__file__).as_posix()
    with pytest.raises(ad.AskError, match="outside the orders table"):
        run(frame, f"SELECT * FROM read_csv('{target}')", guard=False)
    with pytest.raises(ad.AskError):
        run(frame, f"COPY (SELECT 1) TO '{(Path(__file__).parent / 'leak.csv').as_posix()}'", guard=False)
    assert not (Path(__file__).parent / "leak.csv").exists()


def test_extensions_cannot_be_loaded_even_if_the_guard_were_bypassed(frame):
    with pytest.raises(ad.AskError):
        run(frame, "LOAD httpfs", guard=False)
    with pytest.raises(ad.AskError):
        run(frame, "INSTALL httpfs", guard=False)


def test_the_configuration_is_locked_even_if_the_guard_were_bypassed(frame):
    with pytest.raises(ad.AskError):
        run(frame, "SET enable_external_access = true", guard=False)
    with pytest.raises(ad.AskError):
        run(frame, "SET lock_configuration = false", guard=False)


def test_a_destructive_statement_cannot_affect_the_next_query(frame):
    # Without the guard, a DROP can run, but it only touches a throwaway connection.
    try:
        run(frame, "DROP VIEW IF EXISTS orders", guard=False)
    except ad.AskError:
        pass
    assert run(frame, "SELECT count(*) AS n FROM orders").table["n"].tolist() == [10]


def test_the_data_frame_is_never_changed_by_a_query(frame):
    before = frame.copy()
    for sql in ("SELECT * FROM orders", "SELECT sum(order_value) FROM orders"):
        run(frame, sql)
    pd.testing.assert_frame_equal(frame, before)


# ----------------------------------------------------------------------- limits

def test_a_runaway_query_is_stopped_by_the_time_limit(frame):
    sql = "WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM t) SELECT count(*) FROM t"
    with pytest.raises(ad.AskError, match="too long"):
        run(frame, sql, timeout=0.5)


def test_a_huge_result_is_cut_at_the_row_cap(frame):
    big = pd.concat([frame] * 300, ignore_index=True)
    out = run(big, "SELECT customer_id, order_value FROM orders", max_rows=500)
    assert len(out.table) == 500 and out.truncated is True
    small = run(frame, "SELECT * FROM orders", max_rows=500)
    assert len(small.table) == 10 and small.truncated is False


def test_the_row_cap_keeps_the_query_order(frame):
    out = run(frame, "SELECT order_value FROM orders ORDER BY order_value DESC", max_rows=3)
    assert out.table["order_value"].tolist() == [100, 90, 80] and out.truncated


def test_bad_sql_gives_a_short_readable_message(frame):
    with pytest.raises(ad.AskError, match="did not run"):
        run(frame, "SELECT no_such_column FROM orders")


# --------------------------------------------------------- legitimate queries

def test_plain_queries_ctes_joins_and_window_functions_work(frame):
    assert run(frame, "SELECT count(*) AS n, sum(order_value) AS total FROM orders").table.iloc[0].tolist() == [10, 580]
    cte = run(frame, "WITH t AS (SELECT customer_id, sum(order_value) AS s FROM orders GROUP BY 1) SELECT max(s) AS biggest FROM t")
    assert cte.table["biggest"].tolist() == [200]
    join = run(frame, "SELECT count(*) AS n FROM orders a JOIN orders b ON a.customer_id = b.customer_id")
    assert join.table["n"].tolist() == [3 * 3 + 2 * 2 + 1 + 2 * 2 + 2 * 2]  # pairs within each customer
    window = run(frame, "SELECT customer_id, row_number() OVER (PARTITION BY customer_id ORDER BY order_date) AS n FROM orders WHERE customer_id = 'A'")
    assert window.table["n"].tolist() == [1, 2, 3]


def test_harmless_words_are_not_mistaken_for_commands(frame):
    # The guard reads the parsed query, not the text, so quoted words and aliases are fine.
    ok = run(frame, "SELECT customer_id AS reset_count_label, 'drop table copy' AS note, 1 AS load FROM orders LIMIT 1")
    assert ok.table.columns.tolist() == ["reset_count_label", "note", "load"] and len(ok.table) == 1


def test_a_table_alias_and_a_qualified_orders_reference_are_fine(frame):
    assert run(frame, "SELECT count(*) AS n FROM main.orders AS o").table["n"].tolist() == [10]


def test_a_cte_named_like_something_else_is_fine_but_a_real_other_table_is_not(frame):
    ok = run(frame, "WITH recent AS (SELECT * FROM orders WHERE order_value > 50) SELECT count(*) AS n FROM recent")
    assert ok.table["n"].tolist() == [5]  # the orders above 50 are 100, 60, 80, 70 and 90
    with pytest.raises(ad.AskError, match="Only the orders table"):
        run(frame, "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent, secrets")


# --------------------------------------------------------- the ready-made questions

def test_every_ready_made_question_runs_and_is_a_single_select(frame):
    for name, sql in ad.PRESETS.items():
        assert ad.guard_sql(sql) == sql
        out = ad.run_preset(frame, name)
        assert len(out.table) >= 1 and not out.truncated


def test_top_customers_by_spend_matches_the_hand_count(frame):
    t = ad.run_preset(frame, "Top 10 customers by spend").table
    # A 200 first, then B 100, D 100, E 100 in id order, then C 80.
    assert t["customer_id"].tolist() == ["A", "B", "D", "E", "C"]
    assert t["total_spend"].tolist() == [200, 100, 100, 100, 80] and t["orders"].tolist() == [3, 2, 2, 2, 1]


def test_orders_and_revenue_by_month_match_the_hand_count(frame):
    t = ad.run_preset(frame, "Orders and revenue by month").table
    assert t["month"].tolist() == ["2024-01", "2024-02", "2024-04", "2024-05", "2024-06"]  # March had no orders
    assert t["orders"].tolist() == [3, 3, 1, 2, 1] and t["revenue"].tolist() == [200, 160, 50, 160, 10]
    assert t["revenue"].sum() == 580


def test_average_order_value_by_month_matches_the_hand_count(frame):
    t = ad.run_preset(frame, "Average order value by month").table
    assert t["average_order_value"].tolist() == [round(200 / 3, 2), round(160 / 3, 2), 50, 80, 10]


def test_repeat_rate_by_first_order_month_matches_the_hand_count(frame):
    t = ad.run_preset(frame, "Repeat rate by first order month").table
    # January cohort A and B both repeat, February C and D with only D repeating, May E repeats.
    assert t["first_month"].tolist() == ["2024-01", "2024-02", "2024-05"]
    assert t["customers"].tolist() == [2, 2, 1] and t["repeat_customers"].tolist() == [2, 1, 1]
    assert t["repeat_percent"].tolist() == [100.0, 50.0, 100.0]


def test_the_biggest_orders_and_most_orders_presets(frame):
    biggest = ad.run_preset(frame, "Biggest single orders").table
    assert biggest["order_value"].tolist()[:3] == [100, 90, 80]
    most = ad.run_preset(frame, "Customers with the most orders").table
    assert most["customer_id"].tolist()[0] == "A" and most["orders"].tolist()[0] == 3


def test_an_unknown_ready_made_question_is_refused(frame):
    with pytest.raises(ad.AskError, match="ready-made"):
        ad.run_preset(frame, "Delete everything")


# ---------------------------------------------------------------- AI to query

def fake(reply):
    def call(prompt):
        call.prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    call.prompts = []
    return call


def test_the_prompt_has_the_schema_and_the_question_but_no_data(frame):
    ai = fake(json.dumps({"title": "Total", "sql": "SELECT sum(order_value) AS total FROM orders"}))
    ad.ask(frame, "What is the total?", ai)
    prompt = ai.prompts[0]
    assert "- customer_id (VARCHAR)" in prompt and "- order_value (DOUBLE)" in prompt and "Question: What is the total?" in prompt
    for value in ("580", "2024-01-10", "100.0"):
        assert value not in prompt
    for customer in ("'A'", "Customer A"):
        assert customer not in prompt


def test_an_ai_query_is_checked_and_run_locally(frame):
    ai = fake(json.dumps({"title": "Total spend", "sql": "SELECT sum(order_value) AS total FROM orders"}))
    answer = ad.ask(frame, "What is the total spend?", ai)
    assert answer.title == "Total spend" and answer.result.table["total"].tolist() == [580]
    assert answer.result.sql.startswith("SELECT sum(order_value)")


def test_a_dangerous_ai_query_is_refused_and_never_runs(frame):
    ai = fake(json.dumps({"title": "Oops", "sql": "DROP TABLE orders"}))
    with pytest.raises(ad.AskError, match="Only SELECT"):
        ad.ask(frame, "Delete it", ai)


@pytest.mark.parametrize("reply", ["not json", "[]", '{"title": "x"}', '{"sql": 5}', '{"sql": ""}', '{"sql": "SELECT 1", "title": 4}', None])
def test_a_malformed_ai_reply_is_refused(frame, reply):
    with pytest.raises(ad.AskError, match="not in the expected format"):
        ad.ask(frame, "A question", fake(reply))


def test_a_title_with_a_number_or_an_overclaim_is_replaced(frame):
    ai = fake(json.dumps({"title": "Customers will definitely grow 40%", "sql": "SELECT 1 AS n"}))
    assert ad.ask(frame, "A question", ai).title == "Your question"


def test_question_checks_and_ai_off(frame):
    with pytest.raises(ad.AskError, match="Type a question"):
        ad.ask(frame, "   ", fake("{}"))
    with pytest.raises(ad.AskError, match="under 300"):
        ad.ask(frame, "x" * 301, fake("{}"))
    with pytest.raises(ad.AskError, match="AI is off"):
        ad.ask(frame, "A question", None)


def test_ai_errors_become_friendly_messages(frame):
    with pytest.raises(ad.AskError, match="limit may be used up") as caught:
        ad.ask(frame, "A question", fake(RuntimeError("429 RESOURCE_EXHAUSTED secret-detail")))
    assert "secret-detail" not in str(caught.value)


def test_results_are_never_sent_back_to_the_model(frame):
    ai = fake(json.dumps({"title": "Top", "sql": "SELECT customer_id FROM orders LIMIT 3"}))
    ad.ask(frame, "Who are the customers?", ai)
    assert len(ai.prompts) == 1  # one call, and nothing after the query ran


def test_the_schema_text_follows_the_columns_present(frame):
    with_id = frame.assign(order_id=["o"] * 10)
    assert "- order_id (VARCHAR)" in ad.schema_text(with_id) and "- order_id" not in ad.schema_text(frame)
