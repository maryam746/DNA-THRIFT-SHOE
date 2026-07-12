"""
Quick manual test to confirm the project is set up correctly on your machine.
Run with: python test_inventory.py
"""

from models.shoe_query import ShoeQuery, ShoeSize, SizeSystem, QuerySource
from inventory.lookup import find_match

print("=== Test 1: EXACT MATCH ===")
q = ShoeQuery(
    source=QuerySource.TEXT, brand="Nike", model_name="Air Jordan 1",
    size=ShoeSize(value=10, system=SizeSystem.US),
    raw_input_summary="text: jordan 1 size 10",
)
m = find_match(q)
print("Status:", m.status)
print("Primary:", m.primary_item.product_name, m.primary_item.size_value, "PKR", m.primary_item.price)
print()

print("=== Test 2: PARTIAL MATCH (wrong size) ===")
q2 = ShoeQuery(
    source=QuerySource.TEXT, brand="Nike", model_name="Air Jordan 1",
    size=ShoeSize(value=13, system=SizeSystem.US),
    raw_input_summary="text: jordan 1 size 13",
)
m2 = find_match(q2)
print("Status:", m2.status)
print("Alternatives offered:", [(a.size_value, a.condition_score, a.price) for a in m2.alternatives])
print()

print("=== Test 3: NO MATCH ===")
q3 = ShoeQuery(
    source=QuerySource.TEXT, brand="Puma", model_name="Suede Classic",
    raw_input_summary="text: puma suede size 9",
)
m3 = find_match(q3)
print("Status:", m3.status, "| has_actionable_result:", m3.has_actionable_result)

print()
print("If you see EXACT_MATCH, PARTIAL_MATCH, and NO_MATCH above with no errors, setup is working correctly.")
