"""
Tests the NLP text parser against the REAL Groq API. Run with:
    python test_nlp.py

Requires GROQ_API_KEY to be set in your environment first:
    setx GROQ_API_KEY "your-key-here"
Then RESTART your terminal (setx only applies to new terminal sessions).
"""

from nlp.parser import parse_text_query, ParseFailure

test_messages = [
    "hi do you have air jordan 1 in size 10",
    "looking for some jordans, dont know my exact size rn",
    "what are your store hours",
]

for msg in test_messages:
    print(f"Customer: {msg!r}")
    try:
        q = parse_text_query(msg)
        print(f"  -> brand={q.brand}, model={q.model_name}, size={q.size.value} {q.size.system.value}, "
              f"identifiable={q.is_identifiable}, needs_size={q.needs_size_clarification}")
    except ParseFailure as e:
        print(f"  -> ParseFailure: {e}")
    print()

print("If all three messages produced sensible output above (especially the")
print("2nd correctly leaving size as None, and the 3rd having no brand/model),")
print("the real Groq integration is working correctly.")
