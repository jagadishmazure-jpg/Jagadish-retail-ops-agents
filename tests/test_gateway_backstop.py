"""Gateway bypasses found in review (2026-10-18); each used to succeed.

Before the SQLite-authorizer backstop, check() only inspected names that
followed FROM/JOIN plus whitespace, and the LIMIT cap could be hidden behind
a trailing comment.
"""
import sqlite3

import pytest

from retail import views
from retail.views import SecurityError


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    views.bootstrap(c, seed=42)
    yield c
    c.close()


@pytest.mark.parametrize("sql", [
    "SELECT * FROM v_stock_status, stores",                 # comma join
    'SELECT name, sql FROM "sqlite_master"',                # quoted schema table
    "SELECT * FROM/**/stores",                              # comment as whitespace
    "SELECT * FROM v_stock_status JOIN/**/sales",
])
def test_base_table_and_schema_reads_are_denied(conn, sql):
    with pytest.raises(SecurityError) as err:
        views.run_query(conn, sql)
    assert err.value.rule_id == "SEC-VIEW-03"


@pytest.mark.parametrize("tail", [
    "LIMIT 100000 -- trailing comment hid the appended cap",
    "LIMIT 100000/**/",
    "LIMIT 100000 OFFSET 0",
    "LIMIT 0, 100000",
])
def test_caller_limit_cannot_exceed_the_cap(conn, tail):
    sql = f"SELECT a.sku FROM v_stock_status a JOIN v_stock_status b {tail}"
    assert len(views.run_query(conn, sql)) == views.MAX_LIMIT


def test_literal_containing_limit_still_gets_the_cap(conn):
    sql = ("SELECT a.sku FROM v_stock_status a JOIN v_stock_status b "
           "WHERE a.sku <> 'limit'")
    assert len(views.run_query(conn, sql)) == views.MAX_LIMIT


def test_every_view_still_readable(conn):
    for view in views.VIEW_SQL:
        views.run_query(conn, f"SELECT * FROM {view}")


def test_authorizer_is_removed_after_the_query(conn):
    views.run_query(conn, "SELECT * FROM v_stock_status")
    assert conn.execute("SELECT count(*) FROM stores").fetchone()[0] > 0
