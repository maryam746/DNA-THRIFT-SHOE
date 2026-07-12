"""
The orchestrator: takes one incoming (parsed) WhatsApp message, runs it
through the state machine + NLP/vision + inventory, and produces a reply.

THIS IS THE ONLY FILE THAT KNOWS ABOUT ALL THE OTHER MODULES AT ONCE.
webhook/ doesn't know about inventory. nlp/ doesn't know about vision.
inventory/ doesn't know about conversation state. This file is where those
worlds meet -- which is exactly why it stays thin: it calls out to each
module's single public entry point and lets THIS module's job be purely
"what happens next," never "how do I parse a photo" or "how do I compute
a discount." Those decisions live in their own modules.

CONVERSATION STORAGE NOTE:
Conversations are kept in a plain in-memory dict here, keyed by phone
number. This is fine for local testing/demo purposes, but in a real
deployment this would be a table in dna_thrift.db (or Redis) so state
survives a server restart and works across multiple server processes. This
is a known simplification worth stating plainly in your README rather than
hiding it -- it's a reasonable scope cut for a 1-week project, not an
oversight.
"""

from __future__ import annotations

from conversation.state_machine import (
    ConversationContext,
    ConversationState,
    handle_lookup_result,
    handle_missing_size,
    handle_size_resolved,
    start_new_query,
    transition,
)
from inventory.lookup import find_match
from models.inventory_match import InventoryMatch, MatchStatus
from models.shoe_query import ShoeQuery
from models.webhook import IncomingMessage, MessageType
from nlp.parser import ParseFailure, parse_text_query
from vision.extractor import VisionExtractionFailure, extract_query_from_photo

# In-memory conversation store: phone_number -> ConversationContext.
# See module docstring re: why this isn't a DB table (yet).
_conversations: dict[str, ConversationContext] = {}


def _get_context(phone_number: str) -> ConversationContext:
    if phone_number not in _conversations:
        _conversations[phone_number] = ConversationContext(phone_number=phone_number)
    return _conversations[phone_number]


def _format_price(price: float) -> str:
    return f"Rs. {price:,.0f}"


def _reply_for_match(match: InventoryMatch) -> str:
    """Builds the customer-facing text for an inventory lookup result.
    Kept as plain string templates rather than another LLM call -- once we
    HAVE structured data (an InventoryMatch), turning it into a sentence is
    a deterministic formatting job, not something that benefits from an
    LLM's flexibility. Spending an API call here would just be slower and
    less predictable for zero benefit."""

    if match.status == MatchStatus.EXACT_MATCH and match.primary_item:
        item = match.primary_item
        reply = (
            f"Found it! {item.product_name}, size {item.size_value} {item.size_system}, "
            f"condition {item.condition_score}/10 -- {_format_price(item.price)}. "
        )
        reply += "In stock!" if item.stock_status.value == "in_stock" else "Only one left, grab it fast!"
        if match.alternatives:
            reply += f" We also have {len(match.alternatives)} other condition option(s) at this size if you'd like to see them."
        return reply

    if match.status == MatchStatus.PARTIAL_MATCH and match.alternatives:
        sizes = ", ".join(f"{a.size_value} {a.size_system} ({_format_price(a.price)})" for a in match.alternatives[:3])
        return (
            f"We don't have that exact size in stock right now, but we do have it in: {sizes}. "
            f"Want me to check any of those?"
        )

    return (
        "Sorry, we don't currently carry that model. Want to browse our available categories instead, "
        "or ask about a different shoe?"
    )


REPLY_ASK_FOR_SIZE = "What size are you looking for? (US/UK/EU sizing all work)"
REPLY_ASK_FOR_SHOE = "Hi! Tell me the brand/model you're looking for, or send a photo of a shoe and I'll identify it."
REPLY_UNSUPPORTED_TYPE = "I can only read text messages or photos right now -- could you send one of those?"
REPLY_HUMAN_HANDOFF = (
    "I'm having trouble pinning down the details -- let me connect you with one of our team members "
    "who can help directly. In the meantime, feel free to browse our categories."
)


def process_message(message: IncomingMessage) -> str:
    """
    The single public entry point conversation/ exposes. webhook/app.py
    calls this after parsing the raw payload. Returns the reply text to
    send back to the customer.
    """
    ctx = _get_context(message.from_number)

    # Handle unsupported message types (voice notes, etc.) immediately --
    # this never touches the state machine at all, since it's not a shoe
    # query attempt of any kind.
    if message.message_type == MessageType.UNSUPPORTED:
        return REPLY_UNSUPPORTED_TYPE

    # Fresh conversation: move out of AWAITING_QUERY into IDENTIFYING_SHOE
    # before attempting to parse anything.
    if ctx.state == ConversationState.AWAITING_QUERY:
        ctx = transition(ctx, ConversationState.IDENTIFYING_SHOE)

    # --- Extract a ShoeQuery from whichever input type we got ---
    query: ShoeQuery | None = None
    if message.message_type == MessageType.TEXT and message.text:
        try:
            query = parse_text_query(message.text.body)
        except ParseFailure:
            # Treat an LLM/parse failure the same as an unidentifiable
            # query -- not the customer's fault, but we still can't
            # proceed, so route through the same clarification path.
            query = None
    elif message.message_type == MessageType.IMAGE and message.image:
        # NOTE: in the real webhook flow, message.image.id is a WhatsApp
        # media ID, not a local file path -- resolving that into an actual
        # downloadable image file happens in webhook/media.py (not yet
        # built). For local testing, image.id is treated as a direct file
        # path so we can exercise this code path with real image files.
        try:
            query = extract_query_from_photo(message.image.id)
        except VisionExtractionFailure:
            query = None

    if query is None or not query.is_identifiable:
        # Couldn't identify a shoe at all -- this is where loop-prevention
        # applies, same counter used for missing-size clarification, since
        # both represent "the bot couldn't make progress on this turn."
        ctx = handle_missing_size(ctx)
        if ctx.state == ConversationState.HUMAN_HANDOFF:
            return REPLY_HUMAN_HANDOFF
        return REPLY_ASK_FOR_SHOE

    ctx.pending_query = query

    # --- Size known? If not, ask (with loop-prevention) ---
    if query.needs_size_clarification:
        ctx = handle_missing_size(ctx)
        if ctx.state == ConversationState.HUMAN_HANDOFF:
            return REPLY_HUMAN_HANDOFF
        return REPLY_ASK_FOR_SIZE

    if ctx.state == ConversationState.AWAITING_SIZE_CONFIRMATION:
        # We were previously waiting on a size and just got one -- this is
        # the only case where a transition back into IDENTIFYING_SHOE is
        # both needed and legal.
        ctx = handle_size_resolved(ctx)
    else:
        # Size was known on the very first attempt (ctx.state is already
        # IDENTIFYING_SHOE) -- no transition needed, just reset the streak
        # counter for consistency (mirrors what handle_size_resolved does).
        ctx.clarification_attempts = 0

    # --- Run the inventory lookup ---
    match = find_match(query)
    ctx = handle_lookup_result(ctx, match)

    if ctx.state == ConversationState.HUMAN_HANDOFF:
        return REPLY_HUMAN_HANDOFF

    reply = _reply_for_match(match)

    # After presenting a result, reset toward a fresh query -- keeps the
    # bot ready for "what about a different shoe" without manual reset.
    start_new_query(ctx)

    return reply
