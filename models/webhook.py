"""
Pydantic models for incoming WhatsApp Business Cloud API webhook payloads.

WHY THIS FILE EXISTS:
The WhatsApp webhook sends a deeply nested JSON blob (their format, not ours).
Nothing downstream in this codebase should ever touch that raw dict. The moment
it hits our server, we parse it into these models. If parsing fails, we drop
the payload and log it -- we never pass a raw dict deeper into the system.

WhatsApp's real payload shape (simplified) looks like:
{
  "entry": [{
    "changes": [{
      "value": {
        "messages": [{
          "from": "923001234567",
          "id": "wamid.xxx",
          "timestamp": "1720000000",
          "type": "text" | "image",
          "text": {"body": "..."},
          "image": {"id": "media-id", "mime_type": "image/jpeg", "sha256": "..."}
        }]
      }
    }]
  }]
}

We don't try to model every field Meta could ever send (that's a losing game
and not what the assignment is testing). We model exactly what we need, and
anything unexpected either gets ignored (extra="ignore") or causes validation
to fail loudly, depending on the field.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageType(str, Enum):
    """The two message kinds this bot cares about. Anything else (audio,
    location, sticker, etc.) is treated as unsupported and handled by the
    conversation layer with a polite fallback -- not silently dropped."""

    TEXT = "text"
    IMAGE = "image"
    UNSUPPORTED = "unsupported"


class TextBody(BaseModel):
    """The 'text' object WhatsApp sends for type=text messages."""

    model_config = ConfigDict(extra="ignore")

    body: str = Field(min_length=1, description="Raw text the customer typed")


class ImageBody(BaseModel):
    """The 'image' object WhatsApp sends for type=image messages.

    NOTE: WhatsApp does not send the image bytes directly in the webhook --
    it sends a media 'id' that we must exchange for a download URL via a
    separate authenticated GET to the Graph API. That exchange happens in
    webhook/media.py (later), not here. This model just captures what the
    webhook itself gave us.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="Media ID to resolve into a download URL")
    mime_type: str | None = None
    sha256: str | None = None


class IncomingMessage(BaseModel):
    """A single normalized incoming message, extracted from WhatsApp's nested
    envelope. This is the object every other module actually works with --
    nobody downstream needs to know WhatsApp wraps things in entry/changes/value.
    """

    model_config = ConfigDict(extra="ignore")

    from_number: str = Field(min_length=5, description="Sender's WhatsApp number, E.164-ish")
    message_id: str
    timestamp: str
    message_type: MessageType
    text: TextBody | None = None
    image: ImageBody | None = None

    @field_validator("message_type", mode="before")
    @classmethod
    def _coerce_unknown_types(cls, v: str) -> str:
        """WhatsApp can send message types we don't support (audio, video,
        location, contacts, stickers...). Rather than raising a validation
        error and dropping the whole payload -- which would look like a bug
        to the customer, who just gets silence -- we coerce anything we
        don't explicitly handle into UNSUPPORTED. The conversation layer
        then replies with a friendly "I can only handle text or photos"
        message instead of the request vanishing.
        """
        if v in (MessageType.TEXT.value, MessageType.IMAGE.value):
            return v
        return MessageType.UNSUPPORTED.value

    @property
    def has_valid_payload(self) -> bool:
        """A text message must actually carry a TextBody, an image message
        must actually carry an ImageBody. WhatsApp *shouldn't* send a
        type=text message with no text field, but 'shouldn't' isn't a
        guarantee -- we check explicitly rather than assuming."""
        if self.message_type == MessageType.TEXT:
            return self.text is not None
        if self.message_type == MessageType.IMAGE:
            return self.image is not None
        return True  # UNSUPPORTED messages have no required payload


class WhatsAppWebhookPayload(BaseModel):
    """
    Top-level model for what our /webhook route receives.

    We deliberately do NOT model this as a 1:1 mirror of Meta's full nested
    structure at the top level. Instead, webhook/parser.py is responsible for
    reaching into the raw dict, pulling out the message(s), and constructing
    this flattened model. This keeps every OTHER module blissfully unaware
    of Meta's entry/changes/value nesting.

    This model represents ONE extracted message plus enough context
    (business phone number ID) to reply to it.
    """

    model_config = ConfigDict(extra="ignore")

    object: Literal["whatsapp_business_account"]
    phone_number_id: str = Field(description="Our business number's ID, used when sending replies")
    message: IncomingMessage
