"""
Merges the two vision signals -- OCR's size-tag read and the vision model's
brand/model/condition read -- into one ShoeQuery. This is the photo-path
equivalent of nlp/parser.py: the single function inventory/ and
conversation/ actually call for a photo-based query.

WHY MERGE HERE RATHER THAN LET EACH SUB-MODULE BUILD ITS OWN ShoeQuery:
OCR knows nothing about brand/condition; the vision model knows nothing
about the size tag. Neither one should be constructing a ShoeQuery on its
own, since a ShoeQuery represents the FULL merged understanding of the
photo. This function is the one place that decision happens.
"""

from __future__ import annotations

import os

from models.shoe_query import QuerySource, ShoeQuery
from vision.ocr import read_size_tag
from vision.vision_model import VisionCallError, analyze_shoe_photo


class VisionExtractionFailure(ValueError):
    """Raised only for outright failures (API/network error on the vision
    model call). A photo that simply can't be identified is NOT a failure
    -- it's a valid ShoeQuery with brand=None, model_name=None, handled by
    the conversation layer exactly like an unidentifiable text query."""


def extract_query_from_photo(image_path: str) -> ShoeQuery:
    """
    Public entry point for the photo path. Runs OCR and the vision model
    independently (they don't depend on each other's output), then merges
    results into one ShoeQuery.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise VisionExtractionFailure("GROQ_API_KEY not set -- cannot analyze photo.")

    # OCR runs regardless of whether the vision model succeeds -- these are
    # independent signals, and a vision-model outage shouldn't also block
    # us from at least reading a size tag if one was clearly photographed.
    size = read_size_tag(image_path)

    try:
        vision_result = analyze_shoe_photo(image_path, api_key)
    except VisionCallError as e:
        raise VisionExtractionFailure(f"Vision model call failed: {e}") from e

    # If the vision model itself says the size tag isn't visible in frame,
    # but OCR somehow returned a value anyway, we trust OCR's own
    # confidence check over the vision model's framing judgment -- OCR
    # already has its own "don't guess" logic (vision/ocr.py), so we don't
    # need to second-guess it further here. We only use size_tag_visible as
    # a signal for the SUMMARY text, not to override an OCR result.
    tag_note = "tag visible in frame" if vision_result.size_tag_visible else "tag not visible in frame"

    return ShoeQuery(
        source=QuerySource.PHOTO,
        brand=vision_result.brand,
        model_name=vision_result.model_name,
        size=size,
        condition_tier=vision_result.condition_tier,
        condition_score=vision_result.condition_score,
        raw_input_summary=f"photo: {vision_result.notes} ({tag_note}, OCR size_known={size.is_known})",
    )
