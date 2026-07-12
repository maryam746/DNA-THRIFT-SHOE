"""
InventoryMatch is what inventory/lookup.py hands back to the conversation
layer after querying the database with a ShoeQuery.

WHY THIS ISN'T JUST "return the matching row or None":
The assignment explicitly requires graceful no-match/partial-match handling
("we don't have that exact size, but we have it in size 9 and 11" -- 3.2).
A bare Optional[Row] can't express "no exact match, but here are 2 close
ones." So MatchStatus + a list of alternatives is the whole point of this
model -- it's designed around the THREE outcomes the conversation layer
needs to render differently:
  1. EXACT_MATCH      -> present name/price/stock immediately
  2. PARTIAL_MATCH     -> "not in that size, but available in these"
  3. NO_MATCH          -> "we don't carry that model" (or similar)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MatchStatus(str, Enum):
    EXACT_MATCH = "exact_match"
    PARTIAL_MATCH = "partial_match"
    NO_MATCH = "no_match"


class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"       # e.g. last pair -- lets the bot create urgency honestly
    OUT_OF_STOCK = "out_of_stock"  # listed but currently unavailable


class InventoryItem(BaseModel):
    """A single concrete, purchasable item -- one specific model+size+condition
    combination as it exists in the DB. This is deliberately flat (no nested
    ShoeQuery) because it represents a REAL row, not a request."""

    model_config = ConfigDict(extra="forbid")

    sku: str
    product_name: str = Field(description="Full display name, e.g. 'Nike Air Jordan 1 Retro High OG'")
    brand: str
    size_value: float
    size_system: str
    condition_score: int = Field(ge=1, le=10)
    price: float = Field(gt=0, description="Final price in PKR, already condition-adjusted")
    stock_status: StockStatus
    stock_count: int = Field(ge=0)


class InventoryMatch(BaseModel):
    """
    The complete result of an inventory lookup for a given ShoeQuery.

    `status` drives which conversation template gets used. `primary_item`
    is populated only for EXACT_MATCH. `alternatives` is populated for
    PARTIAL_MATCH (e.g. same model, different sizes/conditions available).
    Both being empty simultaneously with status=NO_MATCH is the valid
    "we genuinely don't carry this" case.
    """

    model_config = ConfigDict(extra="forbid")

    status: MatchStatus
    primary_item: InventoryItem | None = None
    alternatives: list[InventoryItem] = Field(default_factory=list)
    searched_brand: str | None = None
    searched_model: str | None = None

    @property
    def has_actionable_result(self) -> bool:
        """True if there's SOMETHING to show the customer (exact or
        alternatives) rather than a dead end. Used by the conversation
        layer to decide whether to offer a category-browse fallback."""
        return self.primary_item is not None or len(self.alternatives) > 0
