"""
Turns a customer's free-text message into a structured ShoeQuery.

THIS IS PROMPT ENGINEERING APPLIED DIRECTLY -- worth reading the
SYSTEM_PROMPT below closely, since every rule in it maps to something we
discussed: explicit structured JSON output, positive AND negative examples,
telling the model what NOT to do (never guess a missing size), and framing
via role/context.

IMPORTANT ARCHITECTURAL POINT: the LLM's job ends at "produce JSON." This
function is what validates that JSON into a real ShoeQuery via Pydantic --
per spec 3.3, the LLM provides natural-language FLEXIBILITY, but it is
never trusted to make structural decisions unchecked. If the LLM returns
malformed JSON or a JSON shape that fails Pydantic validation, we raise
a distinct error (ParseFailure) rather than silently guessing or crashing
-- the conversation layer catches this and routes to clarification, same
as an unreadable photo would.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from models.shoe_query import ConditionTier, QuerySource, ShoeQuery, ShoeSize, SizeSystem
from nlp.llm_client import LLMCallError, call_groq

SYSTEM_PROMPT = """You are a structured data extractor for a thrift shoe shop's WhatsApp bot.

Extract shoe details from the customer's message and respond with ONLY a JSON object -- no preamble, no markdown code fences, nothing but the JSON itself.

Required JSON shape:
{
  "brand": string or null,
  "model_name": string or null,
  "size_value": number or null,
  "size_system": "US" | "UK" | "EU" or null,
  "wants_to_buy": boolean
}

Rules:
- If the customer does not clearly state a size, set size_value AND size_system to null. NEVER guess or infer a size that wasn't stated -- an absent size must stay absent.
- If a size number is given without a system (e.g. "size 10"), assume "US" only if the customer's phrasing is typical of US sizing conventions; otherwise still set it to "US" as the default assumption for this shop, since our regulars mostly refer to US sizing.
- brand and model_name should be extracted as separate fields when possible (e.g. brand="Nike", model_name="Air Jordan 1"), but if the customer only gives one blended term (e.g. "Jordans"), it is fine to put it in model_name and leave brand null.
- wants_to_buy is true if the customer is asking about availability/price/purchasing, false if they seem to be asking something else entirely (e.g. a general question unrelated to buying a shoe).

Examples:

Customer: "hi do you have air jordan 1 in size 10"
{"brand": "Nike", "model_name": "Air Jordan 1", "size_value": 10, "size_system": "US", "wants_to_buy": true}

Customer: "looking for some jordans, dont know my exact size rn"
{"brand": null, "model_name": "Jordans", "size_value": null, "size_system": null, "wants_to_buy": true}

Customer: "what are your store hours"
{"brand": null, "model_name": null, "size_value": null, "size_system": null, "wants_to_buy": false}
"""


class ParseFailure(ValueError):
    """Raised when the LLM's output can't be turned into a valid ShoeQuery
    -- either malformed JSON or a JSON shape Pydantic rejects. The
    conversation layer treats this exactly like an ambiguous/unreadable
    input: route to clarification, count it toward the loop-prevention
    limit, never silently proceed with guessed data."""


def parse_text_query(customer_text: str) -> ShoeQuery:
    """
    The single public entry point nlp/ exposes. Mirrors vision/extractor.py's
    role for the photo path -- both converge on ShoeQuery, and inventory/
    never knows or cares which one produced it.
    """
    try:
        raw_response = call_groq(SYSTEM_PROMPT, customer_text)
    except LLMCallError as e:
        # An API outage/auth failure is NOT the same as ambiguous input --
        # re-raise as ParseFailure so the conversation layer still has a
        # single exception type to catch, but the underlying cause is
        # preserved for logging.
        raise ParseFailure(f"LLM call failed: {e}") from e

    try:
        extracted = json.loads(raw_response)
    except json.JSONDecodeError as e:
        raise ParseFailure(f"LLM did not return valid JSON: {raw_response[:200]}") from e

    size_value = extracted.get("size_value")
    size_system_str = extracted.get("size_system")

    try:
        size = ShoeSize(
            value=size_value,
            system=SizeSystem(size_system_str) if size_system_str else SizeSystem.UNKNOWN,
        )
        query = ShoeQuery(
            source=QuerySource.TEXT,
            brand=extracted.get("brand"),
            model_name=extracted.get("model_name"),
            size=size,
            condition_tier=ConditionTier.UNKNOWN,  # text queries never carry a condition -- customer is asking, not selling
            condition_score=None,
            raw_input_summary=f"text: {customer_text[:100]}",
        )
    except ValidationError as e:
        raise ParseFailure(f"LLM output failed schema validation: {e}") from e

    return query
