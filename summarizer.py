#!/usr/bin/env python3
"""
summarizer.py
Generates AI summaries for grant entries using Google Gemini.

Usage:
  from summarizer import generate_summary
  grant["summary"] = generate_summary(grant)

Requires GEMINI_API_KEY in a .env file or environment variable.
"""

import os
import re
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Enforce a minimum gap between API calls to stay under the free-tier RPM limit.
# Gemini Flash free tier is ~10 RPM; 7 s between calls gives ~8.5 RPM headroom.
_MIN_CALL_GAP = 7.0
_last_call_time = 0.0


def _rate_limit():
    """Block until at least _MIN_CALL_GAP seconds have passed since the last call."""
    global _last_call_time
    elapsed = time.monotonic() - _last_call_time
    if elapsed < _MIN_CALL_GAP:
        time.sleep(_MIN_CALL_GAP - elapsed)
    _last_call_time = time.monotonic()


def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "429" in msg or "quota" in msg or "rate" in msg or "ratelimit" in msg


def generate_summary(grant: dict) -> str:
    """
    Produce a 2-3 sentence summary for a grant using Gemini.

    Returns the generated summary string, or falls back to the original
    description if all retries are exhausted.
    """
    description = grant.get("description", "").strip()

    prompt = (
        "Write a 2-3 sentence summary of this grant opportunity for a funding "
        "database. Be concise and highlight who can apply, what it funds, and "
        "the geography. Do not use bullet points.\n\n"
        f"Grant: {grant.get('title', '')}\n"
        f"Donor: {grant.get('donor_name', '')}\n"
        f"Geography: {grant.get('geographic_area', '')}\n"
        f"Sector: {grant.get('focus_sector', '')}\n"
        f"Eligibility: {grant.get('eligibility', '')}\n"
        f"Amount: {grant.get('funding_amount', '')}\n"
        f"Deadline: {grant.get('deadline', '')}\n"
    )
    if description:
        prompt += f"\nAdditional context:\n{description}"

    backoff = 60  # initial wait on rate-limit error (seconds)
    for attempt in range(5):
        _rate_limit()
        try:
            response = _client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            if not _is_rate_limit_error(e):
                print(f"    [WARN] Gemini error (non-rate-limit): {e}")
                return description

            # Try to read the suggested retry delay from the error message
            suggested = re.search(r"retrydelay[^\d]*(\d+)", str(e).lower())
            wait = int(suggested.group(1)) + 5 if suggested else backoff
            print(f"    [WARN] Rate limit hit, waiting {wait}s (attempt {attempt+1}/5)...")
            time.sleep(wait)
            backoff = min(backoff * 2, 300)  # exponential backoff, cap at 5 min

    print("    [WARN] All retries exhausted; using raw description as fallback.")
    return description
