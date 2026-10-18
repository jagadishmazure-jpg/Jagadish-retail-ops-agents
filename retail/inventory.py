"""Synthetic retail telemetry store (SQLite).

All data is fictional and seeded for deterministic tests. Day ``0..89`` is the
90-day history window; day ``90`` is "today" (used for active-promotion checks
and sales-velocity windows).

Tables: stores, skus, inventory, sales, returns, suppliers, sku_supplier,
promotions, warehouses, warehouse_stock.

Deterministic edge-case anchors (inserted explicitly after random generation):
- SKU-BEANS-001 stocked out (on_hand = 0) in stores S-001/S-002/S-003 with high
  velocity  -> guaranteed v_stockout_risk rows.
- CUST-ABUSE-99: 14 return events in the last 30 days across 4 stores with
  suspicious reason codes -> guaranteed v_returns_watch row.
- SUP-SLOW-07: lead_time_days = 21, on_time_rate = 0.82 -> supplier risk.
- SKU-PARKA-009: deep overstock (400 units, low velocity) -> markdown candidate.
- PROMO-ANCHOR: active 20%-off promotion on SKU-HEADPH-014 at S-001.
"""

import math
import random
import sqlite3

CURRENT_DAY = 90
VELOCITY_WINDOW_START = 60

SCHEMA = """
CREATE TABLE stores(store_id TEXT PRIMARY KEY, name TEXT, region TEXT, format TEXT);
CREATE TABLE skus(sku TEXT PRIMARY KEY, name TEXT, category TEXT, unit_cost REAL, price REAL);
CREATE TABLE inventory(store_id TEXT, sku TEXT, on_hand INTEGER, reorder_point INTEGER,
    max_stock INTEGER, PRIMARY KEY(store_id, sku));
CREATE TABLE sales(store_id TEXT, sku TEXT, day INTEGER, units INTEGER);
CREATE TABLE returns(store_id TEXT, sku TEXT, customer_id TEXT, day INTEGER,
    units INTEGER, reason_code TEXT);
CREATE TABLE suppliers(supplier_id TEXT PRIMARY KEY, name TEXT, lead_time_days INTEGER,
    on_time_rate REAL);
CREATE TABLE sku_supplier(sku TEXT, supplier_id TEXT, PRIMARY KEY(sku, supplier_id));
CREATE TABLE promotions(promo_id TEXT PRIMARY KEY, sku TEXT, store_id TEXT,
    start_day INTEGER, end_day INTEGER, discount_pct REAL);
CREATE TABLE warehouses(warehouse_id TEXT PRIMARY KEY, region TEXT);
CREATE TABLE warehouse_stock(warehouse_id TEXT, sku TEXT, on_hand INTEGER,
    PRIMARY KEY(warehouse_id, sku));
"""

_STORES = [
    ("S-001", "Downtown LA", "West", "Superstore"),
    ("S-002", "Pasadena", "West", "Neighborhood"),
    ("S-003", "Burbank", "West", "Neighborhood"),
    ("S-004", "Chicago Loop", "Central", "Superstore"),
    ("S-005", "Austin North", "South", "Neighborhood"),
    ("S-006", "Miami Beach", "South", "Superstore"),
    ("S-007", "Seattle Center", "West", "Neighborhood"),
    ("S-008", "Boston Back Bay", "East", "Neighborhood"),
]

# (sku, name, category, unit_cost, price, base daily velocity)
_SKUS = [
    ("SKU-BEANS-001", "Canned Black Beans 15oz", "Grocery", 0.80, 1.49, 9.0),
    ("SKU-RICE-002", "Long Grain Rice 2lb", "Grocery", 1.60, 2.99, 7.5),
    ("SKU-COFFEE-003", "Ground Coffee 12oz", "Grocery", 5.20, 9.99, 6.0),
    ("SKU-MILK-004", "Whole Milk 1gal", "Grocery", 2.10, 3.79, 14.0),
    ("SKU-BREAD-005", "Whole Wheat Bread", "Grocery", 1.10, 2.49, 12.0),
    ("SKU-EGGS-006", "Large Eggs 12ct", "Grocery", 1.90, 3.29, 11.0),
    ("SKU-TEE-007", "Cotton Crew Tee", "Apparel", 4.50, 14.99, 3.2),
    ("SKU-JEANS-008", "Slim Denim Jeans", "Apparel", 18.00, 49.99, 1.8),
    ("SKU-PARKA-009", "Winter Parka", "Apparel", 55.00, 149.99, 0.4),
    ("SKU-SNEAK-010", "Running Sneakers", "Apparel", 28.00, 79.99, 1.5),
    ("SKU-DRESS-011", "Summer Dress", "Apparel", 16.00, 44.99, 1.2),
    ("SKU-HOODIE-012", "Fleece Hoodie", "Apparel", 14.00, 39.99, 2.1),
    ("SKU-PHONE-013", "Smartphone X1", "Electronics", 420.00, 699.99, 0.8),
    ("SKU-HEADPH-014", "Wireless Headphones", "Electronics", 45.00, 129.99, 1.6),
    ("SKU-TABLET-015", "Tablet 10in", "Electronics", 180.00, 329.99, 0.7),
    ("SKU-CHARGE-016", "USB-C Charger 65W", "Electronics", 12.00, 34.99, 2.4),
    ("SKU-SPEAK-017", "Bluetooth Speaker", "Electronics", 30.00, 89.99, 1.1),
    ("SKU-LAMP-018", "LED Desk Lamp", "Home", 15.00, 42.99, 1.0),
    ("SKU-PAN-019", "Nonstick Pan 10in", "Home", 18.00, 54.99, 1.3),
    ("SKU-TOWEL-020", "Bath Towel Set", "Home", 11.00, 32.99, 1.7),
    ("SKU-VAC-021", "Robot Vacuum", "Home", 150.00, 399.99, 0.5),
    ("SKU-CHAIR-022", "Office Chair", "Home", 85.00, 229.99, 0.6),
    ("SKU-PLANT-023", "Indoor Plant Pot", "Home", 8.00, 24.99, 1.9),
    ("SKU-BLANK-024", "Throw Blanket", "Home", 13.00, 36.99, 1.4),
]

_SUPPLIERS = [
    ("SUP-001", "FreshLine Foods", 5, 0.98),
    ("SUP-002", "ApparelCo Direct", 12, 0.96),
    ("SUP-003", "TechSource Inc", 9, 0.97),
    ("SUP-004", "HomeGoods Supply", 11, 0.94),
    ("SUP-005", "ValueMart Wholesale", 7, 0.93),
    ("SUP-SLOW-07", "SlowFreight Logistics", 21, 0.82),
]

_WAREHOUSES = [("W-01", "West"), ("W-02", "Central"), ("W-03", "East")]

_REASON_CODES = ["CHANGED-MIND", "DEFECT", "WRONG-SIZE", "WRONG-ITEM", "DAMAGED"]


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def seed_demo_data(conn, seed=42):
    """Generate the full synthetic dataset. Returns the connection."""
    rng = random.Random(seed)
    init_schema(conn)

    conn.executemany("INSERT INTO stores VALUES (?,?,?,?)", _STORES)
    conn.executemany(
        "INSERT INTO skus(sku,name,category,unit_cost,price) VALUES (?,?,?,?,?)",
        [(s, n, c, uc, p) for (s, n, c, uc, p, _v) in _SKUS],
    )
    conn.executemany("INSERT INTO suppliers VALUES (?,?,?,?)", _SUPPLIERS)
    conn.executemany("INSERT INTO warehouses VALUES (?,?)", _WAREHOUSES)

    velocity = {s: v for (s, _n, _c, _u, _p, v) in _SKUS}
    # supplier links: round-robin by category group, deterministic
    for i, (sku, _n, _c, _u, _p, _v) in enumerate(_SKUS):
        sup = _SUPPLIERS[i % 5][0]
        conn.execute("INSERT INTO sku_supplier VALUES (?,?)", (sku, sup))

    for store_id, _name, _region, _fmt in _STORES:
        for sku, _n, _c, _u, _p, base in _SKUS:
            on_hand = max(0, round(base * rng.uniform(10, 40)))
            reorder_point = max(1, round(base * 7))
            max_stock = max(reorder_point + 1, round(base * 60))
            conn.execute(
                "INSERT INTO inventory VALUES (?,?,?,?,?)",
                (store_id, sku, on_hand, reorder_point, max_stock),
            )
            for day in range(0, CURRENT_DAY):
                weekend = 1.4 if day % 7 in (5, 6) else 1.0
                seasonal = 1.0 + 0.25 * math.sin(day / 14.0)
                units = max(0, round(base * weekend * seasonal + rng.gauss(0, base * 0.25)))
                if units:
                    conn.execute(
                        "INSERT INTO sales VALUES (?,?,?,?)", (store_id, sku, day, units)
                    )
            # sparse background returns
            if rng.random() < 0.35:
                for _ in range(rng.randint(1, 3)):
                    conn.execute(
                        "INSERT INTO returns VALUES (?,?,?,?,?,?)",
                        (
                            store_id, sku,
                            f"CUST-{rng.randint(1000, 9999)}",
                            rng.randint(60, 89), 1,
                            rng.choice(_REASON_CODES),
                        ),
                    )
    for wid, _region in _WAREHOUSES:
        for sku, _n, _c, _u, _p, base in _SKUS:
            conn.execute(
                "INSERT INTO warehouse_stock VALUES (?,?,?)",
                (wid, sku, max(0, round(base * rng.uniform(20, 60)))),
            )
    # a couple of ordinary promotions
    conn.execute(
        "INSERT INTO promotions VALUES (?,?,?,?,?,?)",
        ("PROMO-101", "SKU-TEE-007", "ALL", 70, 84, 15.0),
    )
    conn.execute(
        "INSERT INTO promotions VALUES (?,?,?,?,?,?)",
        ("PROMO-102", "SKU-LAMP-018", "S-004", 75, 89, 10.0),
    )

    _install_anchors(conn)
    conn.commit()
    return conn


def _install_anchors(conn):
    """Deterministic edge cases the tests and demo rely on."""
    # 1) Stockout anchor: beans at zero in 3 stores, with strong velocity.
    for store_id in ("S-001", "S-002", "S-003"):
        conn.execute(
            "UPDATE inventory SET on_hand = 0 WHERE store_id = ? AND sku = 'SKU-BEANS-001'",
            (store_id,),
        )
        for day in range(VELOCITY_WINDOW_START, CURRENT_DAY):
            conn.execute(
                "INSERT INTO sales VALUES (?,?,?,?)", (store_id, "SKU-BEANS-001", day, 9)
            )
    # beans supplied by the slow supplier -> supplier-linked stockout story
    conn.execute("DELETE FROM sku_supplier WHERE sku = 'SKU-BEANS-001'")
    conn.execute("INSERT INTO sku_supplier VALUES ('SKU-BEANS-001','SUP-SLOW-07')")

    # 2) Returns-abuse anchor: 14 events / 30 days / 4 stores, suspicious codes.
    abuse_codes = (["WARDROBE"] * 6 + ["NO-RECEIPT"] * 4 + ["DEFECT"] * 2
                   + ["CHANGED-MIND"] * 2)
    stores_cycle = ("S-001", "S-004", "S-006", "S-002")
    for i, code in enumerate(abuse_codes):
        conn.execute(
            "INSERT INTO returns VALUES (?,?,?,?,?,?)",
            (stores_cycle[i % 4], "SKU-JEANS-008",
             "CUST-ABUSE-99", 76 + (i % 14), 1, code),
        )

    # 3) Overstock anchor: parkas piled up, barely selling.
    conn.execute(
        "UPDATE inventory SET on_hand = 400 WHERE store_id = 'S-004' AND sku = 'SKU-PARKA-009'"
    )

    # 4b) High-value stockout anchor: phones ($420 cost) at zero in 2 stores,
    # so a planner-raised purchase order crosses the $5,000 gate threshold.
    for store_id in ("S-004", "S-006"):
        conn.execute(
            "UPDATE inventory SET on_hand = 0 WHERE store_id = ? AND sku = 'SKU-PHONE-013'",
            (store_id,),
        )

    # 4) Promotion anchor: live 20%-off on headphones at S-001.
    conn.execute(
        "INSERT INTO promotions VALUES (?,?,?,?,?,?)",
        ("PROMO-ANCHOR", "SKU-HEADPH-014", "S-001", 80, 95, 20.0),
    )


def row_counts(conn):
    """Small helper used by tests to assert the seed is deterministic."""
    counts = {}
    for table in ("stores", "skus", "inventory", "sales", "returns", "suppliers",
                  "promotions", "warehouses"):
        counts[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    return counts
