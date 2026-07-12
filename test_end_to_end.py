"""
End-to-end test covering the FOUR scenarios the assignment explicitly
requires the demo recording to show (spec, Deliverables #2):
  1. A text-based query resolving correctly
  2. A photo-based query resolving correctly
  3. An ambiguous case triggering a clarifying question
  4. The loop-prevention fallback triggering

This runs the FULL stack -- webhook parsing, state machine, inventory --
with nlp.parser.parse_text_query and vision.extractor.extract_query_from_photo
mocked (since this sandbox can't reach the real Groq API), so we can prove
the ORCHESTRATION logic is correct independent of live network calls. Run
test_nlp.py and test_vision.py separately (as you've already done) to prove
the real API calls work; this script proves they're wired together correctly.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from models.shoe_query import ConditionTier, QuerySource, ShoeQuery, ShoeSize, SizeSystem
from webhook.app import app
import conversation.handler as handler

client = TestClient(app)


def text_payload(from_number: str, text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "1234567890"},
            "messages": [{"from": from_number, "id": "wamid.x", "timestamp": "1720000000",
                          "type": "text", "text": {"body": text}}],
        }}]}],
    }


def image_payload(from_number: str, media_id: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "1234567890"},
            "messages": [{"from": from_number, "id": "wamid.y", "timestamp": "1720000001",
                          "type": "image", "image": {"id": media_id, "mime_type": "image/jpeg"}}],
        }}]}],
    }


print("=" * 60)
print("SCENARIO 1: Text query resolving correctly (exact match)")
print("=" * 60)
handler._conversations.clear()
with patch("conversation.handler.parse_text_query", return_value=ShoeQuery(
    source=QuerySource.TEXT, brand="Nike", model_name="Air Jordan 1",
    size=ShoeSize(value=10, system=SizeSystem.US),
    raw_input_summary="text: jordan 1 size 10",
)):
    resp = client.post("/webhook", json=text_payload("923001111111", "jordan 1 size 10"))
    print("Reply:", resp.json()["reply"])
print()

print("=" * 60)
print("SCENARIO 2: Photo query resolving correctly")
print("=" * 60)
handler._conversations.clear()
with patch("conversation.handler.extract_query_from_photo", return_value=ShoeQuery(
    source=QuerySource.PHOTO, brand="Adidas", model_name="Samba OG",
    size=ShoeSize(value=8, system=SizeSystem.US),
    condition_tier=ConditionTier.LIGHT_WEAR, condition_score=9,
    raw_input_summary="photo: Adidas Samba, clean condition",
)):
    resp = client.post("/webhook", json=image_payload("923002222222", "media-abc"))
    print("Reply:", resp.json()["reply"])
print()

print("=" * 60)
print("SCENARIO 3: Ambiguous input triggers clarifying question")
print("=" * 60)
handler._conversations.clear()
with patch("conversation.handler.parse_text_query", return_value=ShoeQuery(
    source=QuerySource.TEXT, brand=None, model_name="Jordans",
    size=ShoeSize(),  # no size given
    raw_input_summary="text: looking for jordans",
)):
    resp = client.post("/webhook", json=text_payload("923003333333", "looking for some jordans"))
    print("Reply:", resp.json()["reply"])
print()

print("=" * 60)
print("SCENARIO 4: Loop-prevention fallback triggers after repeated ambiguity")
print("=" * 60)
handler._conversations.clear()
phone = "923004444444"
with patch("conversation.handler.parse_text_query", return_value=ShoeQuery(
    source=QuerySource.TEXT, brand=None, model_name="Jordans",
    size=ShoeSize(),
    raw_input_summary="text: still no size",
)):
    for i in range(1, 4):
        resp = client.post("/webhook", json=text_payload(phone, "idk the size"))
        print(f"Reply {i}:", resp.json()["reply"])
print()
print("(Reply 3 above should be the human handoff message, not another size request)")
