"""
Simulates WhatsApp sending webhook events, WITHOUT needing real Meta API
access. Uses FastAPI's TestClient, which calls the app in-process -- no
server needs to be running separately for this script.

This is a legitimate substitute for the real Meta connection per spec 3.3:
"WhatsApp Business API (or a local webhook simulation of it)". The payload
shapes below are hand-built to exactly match what Meta's real webhook sends,
so this exercises the identical parsing code that would run in production.
"""

from fastapi.testclient import TestClient

from webhook.app import app

client = TestClient(app)


def make_text_payload(from_number: str, text: str, phone_number_id: str = "1234567890") -> dict:
    """Builds a payload shaped exactly like WhatsApp's real webhook JSON
    for an incoming text message."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry-id",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": phone_number_id},
                    "messages": [{
                        "from": from_number,
                        "id": "wamid.test123",
                        "timestamp": "1720000000",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def make_image_payload(from_number: str, media_id: str, phone_number_id: str = "1234567890") -> dict:
    """Same shape, but for an incoming photo (WhatsApp sends a media ID,
    not the image bytes -- resolving that ID into a downloadable image is
    handled separately in webhook/media.py, which we'll build alongside
    the vision pipeline)."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry-id",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": phone_number_id},
                    "messages": [{
                        "from": from_number,
                        "id": "wamid.test456",
                        "timestamp": "1720000001",
                        "type": "image",
                        "image": {"id": media_id, "mime_type": "image/jpeg"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


print("=== Test 1: Valid TEXT message ===")
resp = client.post("/webhook", json=make_text_payload("923001234567", "looking for a used Jordan 1 size 10"))
print("Status:", resp.status_code, "| Body:", resp.json())
print()

print("=== Test 2: Valid IMAGE message ===")
resp2 = client.post("/webhook", json=make_image_payload("923001234567", "real_shoe.jpg"))
print("Status:", resp2.status_code, "| Body:", resp2.json())

print("=== Test 3: MALFORMED payload (missing 'entry' entirely) ===")
malformed = {"object": "whatsapp_business_account", "garbage": "not a real payload"}
resp3 = client.post("/webhook", json=malformed)
print("Status:", resp3.status_code, "| Body:", resp3.json())
print()

print("=== Test 4: Unsupported message type (voice note) ===")
voice_payload = make_text_payload("923001234567", "")
voice_payload["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "audio"
del voice_payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]
resp4 = client.post("/webhook", json=voice_payload)
print("Status:", resp4.status_code, "| Body:", resp4.json())
print()

print("All four scenarios ran. Test 3 should show status=dropped (malformed).")
print("Test 4 should show type=unsupported (not rejected, since it's a valid-but-unhandled message type).")
