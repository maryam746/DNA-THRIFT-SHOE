# DNA Thrift WhatsApp AI Bot

## Demo Video
[Watch the demo here](https://youtu.be/QkrcmqTZx0M)

A conversational AI agent for DNA Thrift (a secondhand shoe shop) that identifies shoes from text or photos, looks them up against real inventory, and replies with name, condition-adjusted price, and availability — via WhatsApp.

Built for the Khizex AI Engineering Internship, Summer 2026.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Setup](#setup)
3. [Environment Variables](#environment-variables)
4. [How the Vision/OCR Pipeline Works](#how-the-visionocr-pipeline-works)
5. [How the Conversation State Machine Works](#how-the-conversation-state-machine-works)
6. [Testing](#testing)
7. [Chosen Multimodal Approach & Limitations](#chosen-multimodal-approach--limitations)
8. [Known Simplifications](#known-simplifications)

---

## Architecture Overview

```
webhook/        WhatsApp webhook receiving + parsing (or local simulation of it)
vision/         Photo analysis: OCR (EasyOCR) + vision model (Groq/Llama 4 Scout)
nlp/            Text query parsing via Groq (llama-3.1-8b-instant)
inventory/      SQLite-backed lookup + condition-adjusted pricing
conversation/   The state machine (deterministic flow control) + orchestration handler
models/         All Pydantic schemas — the validation boundary everything else relies on
```

**Data flow:**

```
Raw WhatsApp JSON
  -> webhook/parser.py         (validated into WhatsAppWebhookPayload; malformed payloads dropped here)
  -> conversation/handler.py   (the orchestrator)
       -> nlp/parser.py  OR  vision/extractor.py   (both produce a ShoeQuery)
       -> conversation/state_machine.py            (decides what state we're in / what's next)
       -> inventory/lookup.py                       (ShoeQuery -> InventoryMatch)
  -> reply text sent back to the customer
```

The core architectural rule (per the assignment spec): **the LLM/vision model is used for natural-language and visual flexibility, but the state machine — plain Python, not an LLM — decides what stage the conversation is in and what's allowed next.** Every state transition is validated against an explicit table (`ALLOWED_TRANSITIONS` in `conversation/state_machine.py`) and illegal transitions raise an error rather than silently happening.

---

## Setup

**Requirements:** Python 3.10+ (developed and tested on 3.14).

```bash
# 1. Install dependencies
pip install pydantic fastapi uvicorn httpx requests easyocr pillow

# 2. Set your Groq API key (see Environment Variables below)

# 3. Initialize the inventory database (creates dna_thrift.db with 10 seed items)
python inventory/db.py

# 4. Run the test suite (see Testing section for what each script covers)
python test_inventory.py
python test_state_machine.py
python test_webhook.py
python test_nlp.py
python test_vision.py
python test_end_to_end.py
```

There is currently no live WhatsApp Business API connection wired in (see [Known Simplifications](#known-simplifications) below) — the webhook layer is fully built and tested via **local simulation**, which the assignment spec explicitly permits (Section 3.3: "Integrate with the WhatsApp Business API *or a local webhook simulation of it*").

---

## Environment Variables

| Variable | Required for | Notes |
|---|---|---|
| `GROQ_API_KEY` | NLP text parsing, vision model calls | Get one free at console.groq.com. On Windows, set with `setx GROQ_API_KEY "your-key"` then **restart your terminal** — `setx` does not apply to the session it was run in. |

---

## How the Vision/OCR Pipeline Works

The photo path has two genuinely independent steps that get merged into one `ShoeQuery` (`vision/extractor.py`):

1. **OCR (`vision/ocr.py`)** — reads the printed size tag using **EasyOCR**, run entirely locally (no API call). Chosen over Tesseract because it's pure Python (no separate system binary/PATH setup needed on Windows) and handles small, low-contrast tag text reasonably well out of the box.

   - Each detected line of text comes with a confidence score. Reads below `MIN_OCR_CONFIDENCE` (0.4) are **discarded**, not trusted — a low-confidence guess is treated the same as no read at all.
   - Regex patterns match common tag formats: `US 9`, `UK 8.5`, `EU 42`, `SIZE 10`, etc.
   - If nothing confident matches, the size is left explicitly unknown (`None`) — the bot then asks the customer to confirm rather than guessing.

2. **Vision model (`vision/vision_model.py`)** — sends the photo to a vision-capable model on Groq (`meta-llama/llama-4-scout-17b-16e-instruct`) to identify brand, model, and assess visible condition (1-10 score + a coarse tier like `light_wear`). Note: Groq's available vision-capable models have changed over the course of this project (an earlier model ID, `llama-3.2-11b-vision-preview`, stopped being available) — worth re-confirming the current model list in Groq's console before any future submission/demo, since this is a fast-moving part of their API surface.

Both steps run independently — a vision model outage doesn't block an OCR read, and vice versa. Their outputs are merged in `extract_query_from_photo()`, which is the single function the rest of the app calls for the photo path.

**Validation boundary:** the vision model's raw JSON output is parsed into a `VisionExtractionResult` Pydantic model *before* anything else touches it. If the model returns an out-of-range value (this happened during testing — a non-shoe test image caused `condition_score: 0`, outside the valid 1–10 range), that invalid response is caught right at this boundary and the pipeline degrades gracefully (treats it as "couldn't assess"), rather than crashing further downstream.

---

## How the Conversation State Machine Works

States (`conversation/state_machine.py`):

```
AWAITING_QUERY -> IDENTIFYING_SHOE -> AWAITING_SIZE_CONFIRMATION -> IDENTIFYING_SHOE (size resolved)
                                   -> PRESENTING_RESULT -> AWAITING_PURCHASE_INTENT
IDENTIFYING_SHOE / AWAITING_SIZE_CONFIRMATION -> HUMAN_HANDOFF (loop-prevention or unidentifiable input)
```

Every legal transition is listed explicitly in `ALLOWED_TRANSITIONS`, a `dict[ConversationState, set[ConversationState]]`. The single function `transition()` is the *only* place `ctx.state` is ever changed, and it raises `TransitionError` for anything not in that table — this was tested directly (see `test_state_machine.py`) to confirm illegal jumps are structurally blocked, not just discouraged by convention.

**Loop-prevention (the specific mechanism the assignment asks to see proven):** a `clarification_attempts` counter increments every time the bot can't make progress on a turn (no size given, or a shoe that can't be identified at all). If this happens more than `MAX_CLARIFICATION_ATTEMPTS` (= 2) times in a row, the state machine forces a transition to `HUMAN_HANDOFF` regardless of what the customer says next — this was demonstrated live in both `test_state_machine.py` (isolated) and `test_end_to_end.py` (through the full webhook flow): three consecutive ambiguous replies produce two clarifying questions followed by a hard cutover to the human-handoff message, never a third repeated question.

The counter resets to 0 on any successful resolution, so a customer who succeeds once isn't left one bad reply away from handoff on an unrelated future question.

---

## Testing

| Script | What it proves |
|---|---|
| `test_inventory.py` | Exact match / partial match / no-match inventory lookups, condition-adjusted pricing |
| `test_state_machine.py` | Loop-prevention firing after 2 failed attempts; illegal transitions rejected; counter resets on success |
| `test_webhook.py` | Valid text/image payloads parsed correctly; malformed payloads dropped cleanly; unsupported message types handled gracefully (not rejected) |
| `test_nlp.py` | Real Groq API call — text query correctly parsed into brand/model/size, with size left unstated when the customer didn't give one |
| `test_vision.py` | Real EasyOCR + real Groq vision model call on an actual photo — see limitations note below |
| `test_end_to_end.py` | All four scenarios the assignment's demo requires: a text query resolving, a photo query resolving, an ambiguous case triggering clarification, and the loop-prevention fallback firing — all through the actual webhook route |

---

## Chosen Multimodal Approach & Limitations

**Text path:** Groq (`llama-3.1-8b-instant`) with a structured-JSON-only system prompt, including explicit few-shot examples and an explicit rule never to guess a size the customer didn't state. Chosen because Gemini's free tier isn't available from Pakistan, and Groq offers fast, low-cost inference with a generous free tier.

**Photo path:** EasyOCR (local, free) for the size tag + Groq's `llama-4-scout-17b-16e-instruct` (a natively multimodal model) for brand/model/condition. Tested against a real shoe photo: the vision model correctly identified brand, model, and condition tier from an actual (not staged) photo. OCR correctly returned "unknown" when the size tag wasn't in frame, rather than fabricating a value.

**Known accuracy limitations (honest, as the assignment asks):**
- OCR reliability depends heavily on tag visibility, lighting, and angle in the photo — a tag that's worn, faint, or out of frame will correctly come back as "unrecognized" rather than guessed, but that means the bot will need to ask for size confirmation on a meaningful fraction of real photos, not just edge cases.
- The vision model's condition scoring is a subjective visual judgment call, not a measured value — two photos of the same shoe from different angles/lighting could plausibly get different condition scores.
- Brand/model identification is strongest for well-known, visually distinctive silhouettes (e.g., Air Jordan 1, Air Force 1) and weaker for generic or less common models.

---

## Known Simplifications

- **Conversation state is stored in-memory** (`conversation/handler.py`), keyed by phone number. In a production deployment this would be a database table so state survives a server restart — a reasonable, explicitly-acknowledged scope cut for a 1-week project, not an oversight.
- **The webhook is tested via local simulation**, not a live Meta WhatsApp Business API connection (permitted explicitly by the assignment spec). The webhook parsing/validation code is written to the exact shape of Meta's real payloads, so connecting a real Meta app later would only require pointing Meta's webhook config at this same `/webhook` route — no application logic would need to change.
- **Media resolution** (turning a WhatsApp media ID into an actual downloadable image file) isn't built yet, since it depends on the live Meta connection above — for local testing, image file paths are passed directly instead.
