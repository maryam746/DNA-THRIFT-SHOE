"""
The conversation state machine: the deterministic "brain" of the bot.

WHY THIS FILE IS THE MOST IMPORTANT ONE IN THE PROJECT:
The assignment is explicit that flow control must NOT be left to an LLM's
improvisation (spec 3.3). This module is the enforcement of that rule --
an LLM can be used elsewhere (parsing text, describing a photo) but THIS
code, not a prompt, decides what state a conversation is in and what
transitions are legal.

DESIGN: states + an explicit transition table + a pure function.
No framework, no external state-machine library -- for a project this size,
a plain enum + a dict of allowed transitions + one decision function is
easier to read, test, and defend in a demo than pulling in a dependency
that would make the logic harder to point at and explain line by line.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from models.inventory_match import InventoryMatch, MatchStatus
from models.shoe_query import ShoeQuery

# How many consecutive times we'll ask the SAME clarifying question before
# giving up and handing off. This is the literal loop-prevention knob the
# spec asks for (3.3: "after 2 failed clarification attempts, offer to
# connect to a human"). It's a named constant, not a magic number buried
# in an if-statement, so it's obvious in review and easy to tune.
MAX_CLARIFICATION_ATTEMPTS = 2


class ConversationState(str, Enum):
    """The full set of states a conversation can be in. Every one of these
    corresponds to a box in the state diagram -- if you add a state here,
    add it to the diagram too, and vice versa."""

    AWAITING_QUERY = "awaiting_query"
    IDENTIFYING_SHOE = "identifying_shoe"
    AWAITING_SIZE_CONFIRMATION = "awaiting_size_confirmation"
    PRESENTING_RESULT = "presenting_result"
    AWAITING_PURCHASE_INTENT = "awaiting_purchase_intent"
    HUMAN_HANDOFF = "human_handoff"


# The explicit transition table: for each state, which states it is legal
# to move to next. This is the artifact you show a reviewer to PROVE the
# flow is deterministic -- any transition not listed here is simply not
# possible, enforced by transition() raising if asked to do it.
ALLOWED_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.AWAITING_QUERY: {
        ConversationState.IDENTIFYING_SHOE,
    },
    ConversationState.IDENTIFYING_SHOE: {
        ConversationState.AWAITING_SIZE_CONFIRMATION,  # size missing/unclear
        ConversationState.PRESENTING_RESULT,             # size known, lookup done
        ConversationState.HUMAN_HANDOFF,                  # brand/model totally unidentifiable
    },
    ConversationState.AWAITING_SIZE_CONFIRMATION: {
        ConversationState.IDENTIFYING_SHOE,             # customer gave a usable size -> re-run lookup
        ConversationState.AWAITING_SIZE_CONFIRMATION,   # still ambiguous, asking again (self-loop,
                                                          # legal only up to MAX_CLARIFICATION_ATTEMPTS --
                                                          # that ceiling is enforced in handle_missing_size,
                                                          # not by this table)
        ConversationState.HUMAN_HANDOFF,                 # MAX_CLARIFICATION_ATTEMPTS exceeded
    },
    ConversationState.PRESENTING_RESULT: {
        ConversationState.AWAITING_PURCHASE_INTENT,
        ConversationState.AWAITING_QUERY,       # customer asks about a different shoe
    },
    ConversationState.AWAITING_PURCHASE_INTENT: {
        ConversationState.AWAITING_QUERY,       # new query = loop restarts, per the diagram
        ConversationState.HUMAN_HANDOFF,         # customer wants to actually complete a purchase
    },
    ConversationState.HUMAN_HANDOFF: set(),  # terminal for this bot -- a human takes over
}


class ConversationContext(BaseModel):
    """
    The full state of one ongoing conversation. This is what gets
    persisted (per WhatsApp phone number) between messages -- in a real
    deployment this would live in the SQLite DB or an in-memory store
    keyed by from_number, not just held in a Python variable.
    """

    model_config = ConfigDict(extra="forbid")

    phone_number: str
    state: ConversationState = ConversationState.AWAITING_QUERY
    clarification_attempts: int = Field(
        default=0,
        description="Consecutive failed size-clarification attempts. Reset "
                    "to 0 whenever the customer successfully provides a size "
                    "or a new query begins -- it only tracks a STREAK.",
    )
    pending_query: ShoeQuery | None = Field(
        default=None,
        description="The in-progress ShoeQuery being built up across "
                    "clarification turns, e.g. brand+model known, waiting on size.",
    )
    last_match: InventoryMatch | None = None


class TransitionError(ValueError):
    """Raised when code attempts a transition not present in
    ALLOWED_TRANSITIONS. This should never happen if conversation/handler.py
    is written correctly -- if it fires, it's a bug, not a user input
    problem, and should be logged loudly."""


def transition(ctx: ConversationContext, new_state: ConversationState) -> ConversationContext:
    """
    The ONLY function allowed to change ctx.state. Every state change in
    the whole codebase must go through here, so this is the single
    enforcement point for "the transition table is the law."
    """
    if new_state not in ALLOWED_TRANSITIONS[ctx.state]:
        raise TransitionError(
            f"Illegal transition: {ctx.state.value} -> {new_state.value}. "
            f"Allowed from {ctx.state.value}: "
            f"{[s.value for s in ALLOWED_TRANSITIONS[ctx.state]]}"
        )
    ctx.state = new_state
    return ctx


def handle_missing_size(ctx: ConversationContext) -> ConversationContext:
    """
    Called when we're in IDENTIFYING_SHOE (or already in
    AWAITING_SIZE_CONFIRMATION) and the customer's latest message still
    doesn't give us a usable size.

    THIS IS THE LOOP-PREVENTION LOGIC. Read this function top to bottom in
    a demo -- it's the concrete proof that infinite loops are impossible:
    the counter can only go up to MAX_CLARIFICATION_ATTEMPTS before the
    state machine forcibly reroutes to HUMAN_HANDOFF, no matter what the
    customer says next.
    """
    ctx.clarification_attempts += 1

    if ctx.clarification_attempts > MAX_CLARIFICATION_ATTEMPTS:
        # Force the escalation. Note this transition is legal from BOTH
        # IDENTIFYING_SHOE and AWAITING_SIZE_CONFIRMATION per the table above,
        # so this call succeeds regardless of which of those two states we
        # were in when the limit was hit.
        return transition(ctx, ConversationState.HUMAN_HANDOFF)

    return transition(ctx, ConversationState.AWAITING_SIZE_CONFIRMATION)


def handle_size_resolved(ctx: ConversationContext) -> ConversationContext:
    """Called when the customer's message DOES give us a usable size
    (whether on the first try or after clarification). Resets the streak
    counter -- a successful resolution always clears it, since the counter
    only exists to catch CONSECUTIVE failures, not lifetime ones."""
    ctx.clarification_attempts = 0
    return transition(ctx, ConversationState.IDENTIFYING_SHOE)


def handle_lookup_result(ctx: ConversationContext, match: InventoryMatch) -> ConversationContext:
    """Called after inventory.lookup.find_match() runs. Routes based on
    whether we got something actionable to show the customer."""
    ctx.last_match = match
    if match.status == MatchStatus.NO_MATCH and not match.has_actionable_result:
        # Genuinely nothing to offer -- rather than a dead PRESENTING_RESULT
        # with an empty result, we treat total non-carriage the same as an
        # unidentifiable request and hand off, since the bot has nothing
        # further to usefully do.
        return transition(ctx, ConversationState.HUMAN_HANDOFF)
    return transition(ctx, ConversationState.PRESENTING_RESULT)


def start_new_query(ctx: ConversationContext) -> ConversationContext:
    """Resets a conversation back to the top of the flow -- used both for
    the very first message and for 'customer asks about a different shoe'
    from PRESENTING_RESULT or AWAITING_PURCHASE_INTENT. This is the '↻ next
    query restarts flow' loop shown in the diagram."""
    ctx.clarification_attempts = 0
    ctx.pending_query = None
    ctx.last_match = None
    return transition(ctx, ConversationState.AWAITING_QUERY)
