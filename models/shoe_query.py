"""
The ShoeQuery model is the single most important type in this codebase.

WHY IT EXISTS:
Both the text path (nlp/) and the photo path (vision/) produce DIFFERENT raw
outputs -- an LLM's parsed intent on one side, a vision model's attribute
extraction + OCR result on the other. Rather than letting inventory/ know
about both of those shapes, both paths converge into THIS one model. From
inventory/'s perspective, it never knows or cares whether the query came from
a typed sentence or a photo. That's the whole point of "structured routing."

Every field that could plausibly be missing/uncertain IS Optional, on
purpose. A photo with an unreadable size tag should NOT force a fake
guessed value in here -- it should leave size=None and let the
conversation layer decide to ask the customer. Silently guessing is exactly
what the assignment spec forbids (3.1: "ask the customer to confirm/provide
the size rather than guessing silently").
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuerySource(str, Enum):
    """Where this query originated. Kept on the model (not just implied by
    which module called it) because the conversation layer's clarification
    wording differs -- e.g. 'the photo tag was hard to read' vs
    'could you tell me the size' -- and it needs to know the source to
    phrase the question naturally."""

    TEXT = "text"
    PHOTO = "photo"


class SizeSystem(str, Enum):
    """Shoe sizes are meaningless without knowing which national sizing
    system they're in. A bare '9' is ambiguous between US/UK/EU. We require
    the system to travel WITH the number everywhere in the codebase --
    never a bare int floating around."""

    US = "US"
    UK = "UK"
    EU = "EU"
    UNKNOWN = "UNKNOWN"


class ConditionTier(str, Enum):
    """A coarse, human-describable condition bucket. We ALSO keep a raw
    1-10 condition_score (below) for pricing math, but the tier exists
    because conversation replies should say 'lightly worn', not '8/10' --
    customers think in adjectives, pricing logic thinks in numbers."""

    LIKE_NEW = "like_new"        # 9-10
    LIGHT_WEAR = "light_wear"    # 7-8
    VISIBLE_WEAR = "visible_wear"  # 4-6
    HEAVY_WEAR = "heavy_wear"    # 1-3
    UNKNOWN = "unknown"


class ShoeSize(BaseModel):
    """Size is its own small model rather than two loose fields, because
    'size present but system unknown' and 'size absent entirely' are
    different states the conversation layer needs to distinguish."""

    model_config = ConfigDict(extra="forbid")

    value: float | None = Field(
        default=None,
        description="Numeric size, e.g. 9.5. None means unreadable/unstated.",
    )
    system: SizeSystem = SizeSystem.UNKNOWN

    @field_validator("value")
    @classmethod
    def _sane_range(cls, v: float | None) -> float | None:
        # Loose sanity bound. Not trying to be a perfect shoe-size validator --
        # just catching OCR garbage like reading "90" off a smudged tag.
        if v is not None and not (1.0 <= v <= 20.0):
            raise ValueError(f"Shoe size {v} outside plausible range (1-20)")
        return v

    @property
    def is_known(self) -> bool:
        return self.value is not None and self.system != SizeSystem.UNKNOWN


class ShoeQuery(BaseModel):
    """
    The normalized, structured shoe request -- the ONLY thing inventory/
    ever receives. Built by nlp/parser.py (from text) or
    vision/extractor.py (from a photo), never constructed ad hoc elsewhere.
    """

    model_config = ConfigDict(extra="forbid")

    source: QuerySource
    brand: str | None = Field(default=None, description="e.g. 'Nike', 'Air Jordan'")
    model_name: str | None = Field(default=None, description="e.g. 'Air Jordan 1 Retro High'")
    size: ShoeSize = Field(default_factory=ShoeSize)
    condition_tier: ConditionTier = ConditionTier.UNKNOWN
    condition_score: int | None = Field(
        default=None, ge=1, le=10,
        description="Raw 1-10 score if available (from photo assessment). "
                    "Null for text queries -- a customer describing a shoe "
                    "they WANT to buy has no condition to report.",
    )
    raw_input_summary: str = Field(
        description="Short human-readable trace of what the customer actually "
                    "said/sent, e.g. 'text: used Jordan 1 size 10' or "
                    "'photo: Nike Air Force 1, tag partially visible'. "
                    "Purely for logging/debugging, never shown to the customer verbatim."
    )

    @property
    def is_identifiable(self) -> bool:
        """Bare minimum to even attempt an inventory lookup: we need at
        least a brand or model name. Size can be missing -- that triggers
        a clarifying question rather than blocking the query entirely."""
        return bool(self.brand or self.model_name)

    @property
    def needs_size_clarification(self) -> bool:
        return not self.size.is_known
