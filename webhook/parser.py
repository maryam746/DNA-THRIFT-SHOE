"""
Parses WhatsApp's raw nested webhook JSON into our flat WhatsAppWebhookPayload
model. This is THE boundary: nothing before this function has any typed
guarantees, nothing after it ever sees a raw dict again.

WHY A SEPARATE PARSER FUNCTION INSTEAD OF A PYDANTIC VALIDATOR ON THE
NESTED SHAPE DIRECTLY:
We could theoretically write nested Pydantic models mirroring Meta's exact
JSON structure and let Pydantic do the whole extraction. We deliberately
don't -- reaching into entry[0].changes[0].value.messages[0] with explicit
Python (and clear error messages when a level is missing) is easier to
read, debug, and explain in a demo than a five-level-deep nested model
tree. This function IS the "flatten Meta's structure" step described in
models/webhook.py's docstring.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from models.webhook import WhatsAppWebhookPayload

logger = logging.getLogger("webhook.parser")


class MalformedPayloadError(ValueError):
    """Raised when a raw webhook payload can't be parsed into our model at
    all -- missing required nesting, wrong object type, etc. The webhook
    route catches this, logs it, and drops the payload with a 200 response
    (per WhatsApp convention: always ack receipt so Meta doesn't retry
    forever, but never process unparseable data)."""


def parse_webhook_payload(raw: dict) -> WhatsAppWebhookPayload:
    """
    Reach into WhatsApp's real nested envelope and construct our flat model.
    Raises MalformedPayloadError for anything that doesn't have the shape
    we need -- this is the "drop malformed payloads cleanly" requirement
    from spec 3.4, made concrete.
    """
    try:
        entry = raw["entry"][0]
        change = entry["changes"][0]
        value = change["value"]
        phone_number_id = value["metadata"]["phone_number_id"]
        message_raw = value["messages"][0]
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("Dropping malformed webhook payload: missing %s", e)
        raise MalformedPayloadError(f"Payload missing expected structure: {e}") from e

    # Build the flattened dict our IncomingMessage model expects. Note we
    # don't blindly pass message_raw through -- we explicitly map only the
    # fields we care about, so unexpected extra fields from Meta never leak
    # into our internal representation.
    incoming_message = {
        "from_number": message_raw.get("from", ""),
        "message_id": message_raw.get("id", ""),
        "timestamp": message_raw.get("timestamp", ""),
        "message_type": message_raw.get("type", "unsupported"),
        "text": message_raw.get("text"),
        "image": message_raw.get("image"),
    }

    try:
        return WhatsAppWebhookPayload(
            object=raw.get("object"),
            phone_number_id=phone_number_id,
            message=incoming_message,
        )
    except ValidationError as e:
        logger.warning("Dropping payload that failed model validation: %s", e)
        raise MalformedPayloadError(str(e)) from e
