"""Rule-based NL -> SQL over the read-only retail views.

Five planner intents, each mapped to a fixed parameterized SELECT template over
the view allowlist. The gateway in views.py enforces SELECT-only, identifier
allowlist, and the LIMIT cap, so generated SQL can never escape the sandbox.

On a database error the planner retries once with a simplified query
(``SELECT * FROM <view> LIMIT 20``) before raising EscalationNeeded.
"""

import re
import sqlite3

from . import views

STOCKOUT_SQL = (
    "SELECT store_id, store_name, sku, sku_name, days_of_cover, on_hand, "
    "reorder_point, unit_cost, supplier_name, lead_time_days, on_time_rate "
    "FROM v_stockout_risk ORDER BY days_of_cover ASC LIMIT 50"
)
OVERSTOCK_SQL = (
    "SELECT store_id, store_name, sku, sku_name, on_hand, days_of_cover, "
    "avg_daily_velocity FROM v_stock_status WHERE days_of_cover > 90 "
    "ORDER BY days_of_cover DESC LIMIT 50"
)
RETURNS_SQL = (
    "SELECT customer_id, return_events, total_units_returned, stores_used, "
    "suspicious_events FROM v_returns_watch "
    "ORDER BY suspicious_events DESC, return_events DESC LIMIT 50"
)
PROMO_SQL = (
    "SELECT store_id, store_name, sku, sku_name, on_promo, promo_discount_pct, "
    "avg_daily_velocity, days_of_cover FROM v_stock_status WHERE on_promo = 1 "
    "ORDER BY avg_daily_velocity DESC LIMIT 50"
)
SUPPLIER_SQL = (
    "SELECT supplier_id, name, lead_time_days, on_time_rate, risk_band "
    "FROM v_supplier_risk ORDER BY on_time_rate ASC LIMIT 50"
)

_TEMPLATES = {
    "stockout_risk": ("v_stockout_risk", STOCKOUT_SQL),
    "overstock_markdown": ("v_stock_status", OVERSTOCK_SQL),
    "returns_abuse": ("v_returns_watch", RETURNS_SQL),
    "promotion_impact": ("v_stock_status", PROMO_SQL),
    "supplier_leadtime": ("v_supplier_risk", SUPPLIER_SQL),
}

_INTENT_PATTERNS = [
    ("stockout_risk", re.compile(r"stock\s*-?\s*out|running out|reorder|at risk|replenish", re.I)),
    ("overstock_markdown", re.compile(r"overstock|markdown|mark\s*-?\s*down|excess|clearance", re.I)),
    ("returns_abuse", re.compile(r"\breturn\b|returns\b|refund|abuse|wardrob", re.I)),
    ("promotion_impact", re.compile(r"promot|discount|campaign|\bsale\b", re.I)),
    ("supplier_leadtime", re.compile(r"supplier|vendor|lead[- ]time|on[- ]time|late deliver", re.I)),
]


class UnknownIntent(Exception):
    """The question matched no governed intent."""


class EscalationNeeded(Exception):
    """Even the simplified retry failed; a human must take over."""


def detect_intents(question):
    """Return every matching intent name, in priority order (fan-out)."""
    return [name for name, pattern in _INTENT_PATTERNS if pattern.search(question)]


def build_sql(intent):
    """Return (sql, params) for an intent. Raises UnknownIntent for bad names."""
    if intent not in _TEMPLATES:
        raise UnknownIntent(intent)
    _view, sql = _TEMPLATES[intent]
    return sql, ()


def run(conn, intent):
    """Execute one intent with a single simplified-query retry on DB errors."""
    view, sql = _TEMPLATES[intent]
    try:
        rows = views.run_query(conn, sql)
    except sqlite3.Error:
        try:
            rows = views.run_query(conn, f"SELECT * FROM {view} LIMIT 20")
            sql = f"SELECT * FROM {view} LIMIT 20  -- simplified retry"
        except sqlite3.Error as exc:
            raise EscalationNeeded(intent) from exc
    return {"intent": intent, "sql": sql, "rows": rows}


def run_question(conn, question):
    """Detect the first intent and run it. Raises UnknownIntent when nothing matches."""
    intents = detect_intents(question)
    if not intents:
        raise UnknownIntent(question)
    return run(conn, intents[0])
