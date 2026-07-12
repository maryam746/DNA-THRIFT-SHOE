"""
Database setup for DNA Thrift's inventory.

WHY SQLite:
Spec explicitly allows SQLite, and for a 1-week internship project it's the
right call -- zero server setup, the whole DB is a single file you can ship
alongside your repo for the demo, and Python's stdlib `sqlite3` needs no
extra dependency.

SCHEMA DESIGN NOTE:
Each row is one PHYSICAL PAIR of shoes -- not a "product" with variants.
This matters for a thrift store specifically: unlike a normal retailer where
one SKU might have 20 identical units in stock, a thrift pair is literally
one specific item with its own unique condition and price. Two "Air Jordan 1
size 10" pairs are NOT interchangeable stock of the same SKU -- one might be
9/10 condition, the other 6/10, at different prices. So `sku` here is unique
per physical pair, not per product line.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "dna_thrift.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    sku TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    brand TEXT NOT NULL,
    model_name TEXT NOT NULL,       -- e.g. "Air Jordan 1 Retro High OG" -- used for matching
    size_value REAL NOT NULL,
    size_system TEXT NOT NULL CHECK(size_system IN ('US', 'UK', 'EU')),
    condition_score INTEGER NOT NULL CHECK(condition_score BETWEEN 1 AND 10),
    base_price REAL NOT NULL CHECK(base_price > 0),  -- price at 10/10 condition
    stock_status TEXT NOT NULL CHECK(stock_status IN ('in_stock', 'low_stock', 'out_of_stock')),
    stock_count INTEGER NOT NULL DEFAULT 1 CHECK(stock_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_brand_model ON inventory(brand, model_name);
"""

SEED_DATA = [
    # (sku, product_name, brand, model_name, size, system, condition, base_price, stock_status, count)
    ("DNA-001", "Nike Air Jordan 1 Retro High OG 'Chicago'", "Nike", "Air Jordan 1 Retro High OG", 10, "US", 9, 45000, "in_stock", 1),
    ("DNA-002", "Nike Air Jordan 1 Retro High OG 'Chicago'", "Nike", "Air Jordan 1 Retro High OG", 9, "US", 6, 32000, "in_stock", 1),
    ("DNA-003", "Nike Air Jordan 1 Retro High OG 'Chicago'", "Nike", "Air Jordan 1 Retro High OG", 11, "US", 7, 36000, "low_stock", 1),
    ("DNA-004", "Nike Air Force 1 '07 White", "Nike", "Air Force 1 '07", 9, "US", 8, 18000, "in_stock", 2),
    ("DNA-005", "Nike Air Force 1 '07 White", "Nike", "Air Force 1 '07", 10, "US", 5, 12000, "in_stock", 1),
    ("DNA-006", "Adidas Ultraboost 22", "Adidas", "Ultraboost 22", 9, "US", 8, 22000, "in_stock", 1),
    ("DNA-007", "Adidas Samba OG Black", "Adidas", "Samba OG", 8, "US", 9, 15000, "in_stock", 1),
    ("DNA-008", "Adidas Samba OG Black", "Adidas", "Samba OG", 9, "US", 7, 12500, "out_of_stock", 0),
    ("DNA-009", "New Balance 550 White/Green", "New Balance", "550", 9, "US", 9, 19000, "in_stock", 1),
    ("DNA-010", "Converse Chuck Taylor All Star", "Converse", "Chuck Taylor All Star", 8, "US", 6, 6500, "in_stock", 3),
]

INSERT_SQL = """
INSERT OR REPLACE INTO inventory
(sku, product_name, brand, model_name, size_value, size_system, condition_score, base_price, stock_status, stock_count)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the schema and load seed data. Safe to re-run -- schema uses
    IF NOT EXISTS and seed uses INSERT OR REPLACE, so this is idempotent."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(INSERT_SQL, SEED_DATA)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH} with {len(SEED_DATA)} seed items.")
