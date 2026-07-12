"""
Inventory matching logic: takes a ShoeQuery, returns an InventoryMatch.

MATCHING STRATEGY (explain-this-in-the-demo version):
1. EXACT_MATCH   -- same model AND same size found in stock.
2. PARTIAL_MATCH -- same model found, but not in the requested size
                    (we show what sizes/conditions ARE available instead
                    of a dead end -- this satisfies spec 3.2's explicit
                    "we don't have that exact size, but we have it in
                    size 9 and 11" requirement).
3. NO_MATCH      -- brand/model not carried at all.

We match on brand+model_name with a loose SQL LIKE rather than requiring an
exact string match, because a customer or vision model might say "Jordan 1"
when the DB has "Air Jordan 1 Retro High OG" -- real-world text is messy and
punishing that with zero results is a bad customer experience. This is a
conscious tradeoff: looser matching risks false positives, but for a
thrift-shop chatbot with a small catalog, false positives are far less
costly than a customer being told "we don't have it" when we actually do.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from models.inventory_match import InventoryItem, InventoryMatch, MatchStatus, StockStatus
from models.shoe_query import ShoeQuery

DB_PATH = Path(__file__).parent / "dna_thrift.db"

# How much price drops per point below 10/10 condition. A straight linear
# discount is simple to explain and defend ("each condition point = 8% off
# the mint-condition price") -- fancier curves aren't worth the complexity
# for a 1-week project and would be harder to justify in a demo.
CONDITION_DISCOUNT_PER_POINT = 0.08


def _condition_adjusted_price(base_price: float, condition_score: int) -> float:
    """10/10 = full base_price. Each point below 10 knocks off 8%, floored
    so a 1/10 shoe never goes to zero or negative."""
    discount = min((10 - condition_score) * CONDITION_DISCOUNT_PER_POINT, 0.6)
    return round(base_price * (1 - discount), -2)  # round to nearest 100 PKR


def _row_to_item(row: sqlite3.Row) -> InventoryItem:
    price = _condition_adjusted_price(row["base_price"], row["condition_score"])
    return InventoryItem(
        sku=row["sku"],
        product_name=row["product_name"],
        brand=row["brand"],
        size_value=row["size_value"],
        size_system=row["size_system"],
        condition_score=row["condition_score"],
        price=price,
        stock_status=StockStatus(row["stock_status"]),
        stock_count=row["stock_count"],
    )


def find_match(query: ShoeQuery, db_path: Path = DB_PATH) -> InventoryMatch:
    """
    The single public entry point inventory/ exposes. Everything else in
    this module is an implementation detail conversation/ never touches.
    """
    if not query.is_identifiable:
        # No brand or model at all -- nothing to search for. This is a
        # NO_MATCH by definition, not an error: the conversation layer
        # should have already asked for more info before calling us, but
        # we defend against it anyway rather than trusting callers blindly.
        return InventoryMatch(status=MatchStatus.NO_MATCH)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()

        # Build a loose search across brand + model_name. We search both
        # fields with the combined query text so "Jordan 1" matches a
        # model_name containing "Jordan 1" even if brand was parsed as None.
        search_terms = " ".join(t for t in [query.brand, query.model_name] if t)
        like_pattern = f"%{search_terms.replace(' ', '%')}%"

        cursor.execute(
            """
            SELECT * FROM inventory
            WHERE (brand || ' ' || model_name) LIKE ?
            ORDER BY condition_score DESC
            """,
            (like_pattern,),
        )
        candidates = [_row_to_item(row) for row in cursor.fetchall()]

        if not candidates:
            return InventoryMatch(
                status=MatchStatus.NO_MATCH,
                searched_brand=query.brand,
                searched_model=query.model_name,
            )

        # Among model matches, look for an exact size match (if a size was given).
        if query.size.is_known:
            exact = [
                c for c in candidates
                if c.size_value == query.size.value and c.size_system == query.size.system.value
            ]
            if exact:
                # If multiple condition tiers exist at this exact size, we
                # surface the best-condition one as primary and the rest as
                # alternatives -- that way a customer isn't hidden from a
                # cheaper, lower-condition option that might suit them better.
                best = exact[0]
                rest = exact[1:] + [c for c in candidates if c.sku != best.sku and c not in exact]
                return InventoryMatch(
                    status=MatchStatus.EXACT_MATCH,
                    primary_item=best,
                    alternatives=rest[:3],  # cap alternatives shown, keep replies scannable
                    searched_brand=query.brand,
                    searched_model=query.model_name,
                )

        # Model exists but not in the requested size (or no size was given
        # at all) -- partial match, surface what IS available.
        return InventoryMatch(
            status=MatchStatus.PARTIAL_MATCH,
            alternatives=candidates[:5],
            searched_brand=query.brand,
            searched_model=query.model_name,
        )
    finally:
        conn.close()
