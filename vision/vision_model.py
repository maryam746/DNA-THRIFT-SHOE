"""
Uses a vision-capable model (via Groq) to describe brand, model, and visible
condition from a shoe photo. This is the "computer vision" half of the
pipeline -- OCR (vision/ocr.py) handles the printed size tag; this handles
everything else a human would see just by looking at the shoe.

WHY THIS IS SEPARATE FROM ocr.py:
Different job, different tool, different failure mode. OCR either finds
readable text or it doesn't -- deterministic-ish. Describing "this looks
like a Nike Air Force 1 in fairly worn condition" is a genuinely different,
fuzzier task that needs a model actually trained to see, not just read
characters. Keeping them as separate modules means either one can be
swapped independently (e.g. if EasyOCR's accuracy is insufficient later,
you could try asking the vision model to also read the tag as a fallback,
without touching this file).

MODEL CHOICE NOTE FOR YOUR README:
Groq has offered vision-capable Llama models (Llama 3.2 Vision variants) on
their API. Confirm the exact current model ID in Groq's docs / console
before your final submission, since available model names on Groq's
platform do change -- swap GROQ_VISION_MODEL below if the name has shifted
by the time you're building this.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models.shoe_query import ConditionTier

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # confirmed available on Groq as of this project; natively multimodal

VISION_SYSTEM_PROMPT = """You are a visual inspector for a thrift shoe shop. Look at the photo and respond with ONLY a JSON object -- no preamble, no markdown fences.

Required JSON shape:
{
  "brand": string or null,
  "model_name": string or null,
  "condition_tier": "like_new" | "light_wear" | "visible_wear" | "heavy_wear" | "unknown",
  "condition_score": integer 1-10,
  "size_tag_visible": boolean,
  "notes": string
}

Rules:
- If you cannot confidently identify the brand or model from the image, set them to null rather than guessing a specific model you're not sure about.
- condition_score should reflect visible wear: 9-10 = looks nearly new, 7-8 = light wear (minor creasing, clean soles), 4-6 = visible wear (scuffs, some sole wear, discoloration), 1-3 = heavy wear (significant damage, worn soles, major scuffing).
- size_tag_visible should be true only if there is a printed size tag/marking actually visible in the frame -- this tells the calling system whether to trust an OCR read attempt or not.
- notes should be a short (under 15 words) plain description of what you see, e.g. "Nike Air Force 1, light creasing on toe box, clean outsole".
"""


class VisionExtractionResult(BaseModel):
    """What the vision model call returns, before it gets merged into a
    ShoeQuery by extractor.py. Kept separate from ShoeQuery itself because
    this represents exactly and only what the vision model claims to see --
    ShoeQuery is the broader structure that also carries OCR results and
    query source, which this model has no business knowing about."""

    model_config = ConfigDict(extra="ignore")

    brand: str | None = None
    model_name: str | None = None
    condition_tier: ConditionTier = ConditionTier.UNKNOWN
    condition_score: int | None = Field(default=None, ge=1, le=10)
    size_tag_visible: bool = False
    notes: str = ""


class VisionCallError(RuntimeError):
    """Distinct from a successful call that simply couldn't identify the
    shoe -- this is for actual API/network/auth failures."""


def _encode_image(image_path: str) -> str:
    return base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")


def analyze_shoe_photo(image_path: str, api_key: str) -> VisionExtractionResult:
    """
    Public entry point. Sends the photo to Groq's vision model, parses the
    JSON response into a validated VisionExtractionResult.

    Raises VisionCallError for network/API failures. Does NOT raise for
    "couldn't identify the shoe" -- that's a normal, valid result (brand=None,
    model_name=None), handled by the conversation layer same as an
    unidentifiable text query.
    """
    image_b64 = _encode_image(image_path)

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_VISION_MODEL,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze this shoe photo."},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                            },
                        ],
                    },
                ],
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise VisionCallError(f"Groq vision API call failed: {e}") from e

    data = response.json()
    try:
        raw_content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise VisionCallError(f"Unexpected Groq response shape: {json.dumps(data)[:200]}") from e

    try:
        parsed = json.loads(raw_content)
        return VisionExtractionResult(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        # A malformed vision response is treated as "couldn't identify
        # anything" rather than crashing -- same philosophy as the NLP
        # parser's ParseFailure, but here we degrade to an empty result
        # since the vision step is one signal among several (OCR is the
        # other), not the sole source of truth for the query.
        return VisionExtractionResult(notes=f"Could not parse vision model output: {raw_content[:100]}")
