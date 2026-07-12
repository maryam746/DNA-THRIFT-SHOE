"""
Thin wrapper around the Groq API (OpenAI-compatible endpoint). Kept
deliberately separate from parser.py -- this file's ONLY job is "send a
prompt, get raw text back." All prompt construction and JSON-to-ShoeQuery
mapping lives in parser.py. This separation means if you ever swap Groq
for a different provider, only this file changes.

WHY GROQ (documented for your README's "chosen approach" section):
Gemini's free tier isn't available from Pakistan, so Groq (running
llama-3.1-8b-instant) is the practical choice here -- fast inference,
generous free tier, and you already have working API integration patterns
from the Vitality Automation pipeline project.
"""

from __future__ import annotations

import json
import os

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


class LLMCallError(RuntimeError):
    """Raised when the Groq API call itself fails (network, auth, rate
    limit) -- distinct from the response being unparseable, which is
    handled separately in parser.py. Keeping these errors distinct matters
    for the conversation layer: an API outage should probably trigger a
    different customer-facing message than 'I couldn't understand that.'"""


def call_groq(system_prompt: str, user_message: str, temperature: float = 0.1) -> str:
    """
    Sends one prompt to Groq, returns the raw text response.

    temperature=0.1 (not 0, not 0.7): we want near-deterministic structured
    output, but 0 exactly can sometimes make small instruction-tuned models
    repeat degenerate patterns. 0.1 is the pragmatic middle ground used
    across your other Groq-based projects.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMCallError(
            "GROQ_API_KEY environment variable not set. "
            "Set it with: setx GROQ_API_KEY \"your-key-here\" (Windows) "
            "then restart your terminal."
        )

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise LLMCallError(f"Groq API call failed: {e}") from e

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMCallError(f"Unexpected Groq response shape: {json.dumps(data)[:200]}") from e
