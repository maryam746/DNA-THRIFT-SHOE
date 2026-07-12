"""
The FastAPI application receiving WhatsApp webhook events.

In production, Meta's servers POST here directly. In local simulation mode
(which is what we're running until real WhatsApp API access is sorted),
we POST to this exact same endpoint ourselves with hand-built payloads
shaped like WhatsApp's real format. THE CODE PATH IS IDENTICAL EITHER WAY
-- that's the whole point of building the webhook layer this way. Nothing
here needs to change when you eventually switch from local testing to a
real Meta connection; only the sender of the HTTP request changes.

GET /webhook exists because that's how Meta verifies your webhook URL when
you register it (a handshake challenge). It's included here even though
we're not using it yet, since it's zero-cost to have and saves you a step
later.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from webhook.parser import MalformedPayloadError, parse_webhook_payload
from conversation.handler import process_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook.app")

app = FastAPI(title="DNA Thrift Bot Webhook")

# Only used for the real Meta handshake later -- pick any string, put the
# same one in Meta's webhook config when you get there.
VERIFY_TOKEN = "dna-thrift-dev-token"


@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta's webhook verification handshake: it sends hub.challenge and
    expects it echoed back verbatim if hub.verify_token matches ours."""
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return JSONResponse(status_code=403, content={"error": "verification failed"})


@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    The actual message-receiving endpoint. Every incoming payload -- real
    or simulated -- goes through parse_webhook_payload() FIRST. Nothing
    downstream (conversation/, inventory/, vision/, nlp/) ever sees the
    raw request body.
    """
    raw = await request.json()

    try:
        payload = parse_webhook_payload(raw)
    except MalformedPayloadError as e:
        # Per spec 3.4: malformed payloads are dropped with a clear log,
        # not silently passed deeper. We still return 200 -- this matches
        # real WhatsApp webhook convention, where Meta retries on non-2xx
        # responses. We don't want Meta hammering us with retries for a
        # payload that will never parse correctly no matter how many times
        # it's resent.
        logger.warning("Malformed payload dropped: %s", e)
        return JSONResponse(status_code=200, content={"status": "dropped", "reason": str(e)})

    logger.info(
        "Parsed message from %s: type=%s",
        payload.message.from_number,
        payload.message.message_type.value,
    )

    reply_text = process_message(payload.message)

    return JSONResponse(
        status_code=200,
        content={
            "status": "received",
            "from": payload.message.from_number,
            "type": payload.message.message_type.value,
            "reply": reply_text,
        },
    )
