"""Least-privilege gateway over the retail telemetry database.

The planner may only issue SELECT statements against four read-only views.
Every denial cites a stable rule ID:

- SEC-SELECT-01: statement is not a SELECT (or smuggles extra statements).
- SEC-WRITE-02:  SELECT text contains a write keyword.
- SEC-VIEW-03:   query references an identifier outside the view allowlist.

String literals are stripped before scanning so that a word like 'insert'
inside a quoted value can never false-positive (a bug class caught in the
sister logistics repo). Result sets are auto-capped at MAX_LIMIT rows.
"""

import re

from . import inventory as inv

MAX_LIMIT = 100

VIEW_SQL = {
    "v_stock_status": """
        SELECT i.store_id, s.name AS store_name, i.sku, k.name AS sku_name,
               k.category, k.unit_cost, i.on_hand, i.reorder_point, i.max_stock,
               COALESCE(v.avg_daily, 0) AS avg_daily_velocity,
               CASE WHEN COALESCE(v.avg_daily, 0) > 0
                    THEN ROUND(i.on_hand / v.avg_daily, 1) END AS days_of_cover,
               CASE WHEN p.promo_id IS NOT NULL THEN 1 ELSE 0 END AS on_promo,
               p.discount_pct AS promo_discount_pct
        FROM inventory i
        JOIN stores s ON s.store_id = i.store_id
        JOIN skus k ON k.sku = i.sku
        LEFT JOIN (SELECT store_id, sku, AVG(units) AS avg_daily FROM sales
                   WHERE day >= 60 GROUP BY store_id, sku) v
               ON v.store_id = i.store_id AND v.sku = i.sku
        LEFT JOIN promotions p ON p.sku = i.sku
               AND (p.store_id = i.store_id OR p.store_id = 'ALL')
               AND 90 BETWEEN p.start_day AND p.end_day
    """,
    "v_stockout_risk": """
        SELECT st.*, sup.supplier_id, sup.name AS supplier_name,
               sup.lead_time_days, sup.on_time_rate
        FROM v_stock_status st
        JOIN sku_supplier ss ON ss.sku = st.sku
        JOIN suppliers sup ON sup.supplier_id = ss.supplier_id
        WHERE st.days_of_cover IS NOT NULL
          AND st.days_of_cover < sup.lead_time_days
    """,
    "v_returns_watch": """
        SELECT customer_id, COUNT(*) AS return_events,
               SUM(units) AS total_units_returned,
               COUNT(DISTINCT store_id) AS stores_used,
               SUM(CASE WHEN reason_code IN ('WARDROBE', 'DEFECT-FRAUD', 'NO-RECEIPT')
                        THEN 1 ELSE 0 END) AS suspicious_events
        FROM returns WHERE day >= 60
        GROUP BY customer_id HAVING COUNT(*) >= 4
    """,
    "v_supplier_risk": """
        SELECT supplier_id, name, lead_time_days, on_time_rate,
               CASE WHEN on_time_rate < 0.90 OR lead_time_days > 14 THEN 'HIGH'
                    WHEN on_time_rate < 0.95 THEN 'MEDIUM'
                    ELSE 'LOW' END AS risk_band
        FROM suppliers
    """,
}

_WRITE_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "attach", "detach", "vacuum", "pragma", "grant", "revoke",
}
_WRITE_PHRASES = ("replace into",)

_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_COMMENT_RE = re.compile(r"--[^\n]*")
_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_FROM_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\s*;?\s*$", re.IGNORECASE)


class SecurityError(Exception):
    def __init__(self, rule_id, reason):
        super().__init__(f"[{rule_id}] {reason}")
        self.rule_id = rule_id
        self.reason = reason


def install_views(conn):
    for name, sql in VIEW_SQL.items():
        conn.execute(f"DROP VIEW IF EXISTS {name}")
        conn.execute(f"CREATE VIEW {name} AS {sql}")
    conn.commit()


def _strip_noise(sql):
    """Remove string literals and -- comments before security scanning."""
    return _COMMENT_RE.sub(" ", _LITERAL_RE.sub(" ", sql))


def check(sql):
    """Raise SecurityError (with cited rule ID) if the SQL is not allowed."""
    cleaned = _strip_noise(sql)
    if ";" in cleaned:
        raise SecurityError("SEC-SELECT-01", "multiple statements are not allowed")
    head = cleaned.lstrip(" \t\n\r(").lower()
    if not head.startswith("select"):
        raise SecurityError("SEC-SELECT-01", "only SELECT statements are permitted")
    tokens = {t.lower() for t in _TOKEN_RE.findall(cleaned)}
    lowered = cleaned.lower()
    if tokens & _WRITE_KEYWORDS or any(p in lowered for p in _WRITE_PHRASES):
        raise SecurityError("SEC-WRITE-02", "write operations are denied on telemetry views")
    for ident in _FROM_RE.findall(cleaned):
        if ident.lower() not in VIEW_SQL:
            raise SecurityError(
                "SEC-VIEW-03",
                f"identifier '{ident}' is not an exposed read-only view",
            )
    return True


def _cap_limit(sql):
    sql = sql.strip().rstrip(";")
    match = _LIMIT_RE.search(sql)
    if match:
        if int(match.group(1)) > MAX_LIMIT:
            sql = _LIMIT_RE.sub(f"LIMIT {MAX_LIMIT}", sql)
        return sql
    return f"{sql} LIMIT {MAX_LIMIT}"


def run_query(conn, sql, params=()):
    """Security-checked SELECT against the allowlisted views. Returns row dicts."""
    check(sql)
    sql = _cap_limit(sql)
    cursor = conn.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def bootstrap(conn, seed=42):
    """Convenience: seed data + install views. Used by the demo and tests."""
    inv.seed_demo_data(conn, seed=seed)
    install_views(conn)
    return conn
