"""
Quick manual test to confirm the conversation state machine works on your
machine. Run with: python test_state_machine.py
"""

from conversation.state_machine import (
    ConversationContext, ConversationState, TransitionError,
    handle_missing_size, handle_size_resolved, transition,
)

print("=== Loop-prevention: 3 consecutive ambiguous replies ===")
ctx = ConversationContext(phone_number="923001234567")
ctx = transition(ctx, ConversationState.IDENTIFYING_SHOE)
for attempt in range(1, 4):
    ctx = handle_missing_size(ctx)
    print(f"Attempt {attempt}: state={ctx.state.value}, counter={ctx.clarification_attempts}")
print("Fallback triggered:", ctx.state == ConversationState.HUMAN_HANDOFF)
print()

print("=== Illegal transition is rejected ===")
ctx2 = ConversationContext(phone_number="923009999999")
try:
    transition(ctx2, ConversationState.PRESENTING_RESULT)
    print("BUG: should have raised")
except TransitionError as e:
    print("Correctly blocked:", e)
print()

print("=== Successful resolution resets the counter ===")
ctx3 = ConversationContext(phone_number="923005555555")
ctx3 = transition(ctx3, ConversationState.IDENTIFYING_SHOE)
ctx3 = handle_missing_size(ctx3)
ctx3 = handle_missing_size(ctx3)
print("After 2 ambiguous replies, counter:", ctx3.clarification_attempts)
ctx3 = handle_size_resolved(ctx3)
print("After a valid size given, counter:", ctx3.clarification_attempts, "state:", ctx3.state.value)

print()
print("If loop prevention fired, the illegal transition was blocked, and the")
print("counter reset correctly above, the state machine is working.")
