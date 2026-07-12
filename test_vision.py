"""
Tests the vision pipeline: OCR (real, local) + vision model (real, via Groq).
Run with: python test_vision.py

NOTE: The very first run will take a minute or two -- EasyOCR downloads its
detection/recognition model weights (~65MB) the first time it's used. This
is a one-time cost; subsequent runs are fast.

Requires:
- GROQ_API_KEY set in your environment (same one used for test_nlp.py)
- Pillow installed: pip install pillow
- A test image -- this script generates a synthetic one automatically.
"""

import os
from PIL import Image, ImageDraw

from vision.ocr import read_size_tag
from vision.extractor import extract_query_from_photo

# Generate a synthetic shoe-tag-like test image so this runs without
# needing a real photo uploaded yet.

test_image_path = "real_shoe.jpg"


print("=== Test 1: OCR only (local, no API needed) ===")
size = read_size_tag(test_image_path)
print(f"Extracted size: {size.value} {size.system.value} | is_known: {size.is_known}")
print()

if os.environ.get("GROQ_API_KEY"):
    print("=== Test 2: Full pipeline (OCR + Groq vision model) ===")
    print("NOTE: the synthetic test image above is just text on a white background,")
    print("not an actual shoe photo -- the vision model likely won't identify a brand/model")
    print("from it. This test mainly confirms the API call itself succeeds end-to-end.")
    print("For a real test, replace test_image_path below with a path to an actual shoe photo.")
    try:
        query = extract_query_from_photo(test_image_path)
        print(f"brand={query.brand}, model={query.model_name}, condition={query.condition_tier.value}")
        print(f"size={query.size.value} {query.size.system.value}")
        print(f"summary: {query.raw_input_summary}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("GROQ_API_KEY not set -- skipping full pipeline test. OCR-only test above still counts.")
