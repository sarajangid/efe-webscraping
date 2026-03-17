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


def generate_summary(grant: dict) -> str:
    """
    Produce a 2-3 sentence summary for a grant.

    - If body text exists (grant["summary"] is populated from scraping),
      Gemini rephrases it concisely.
    - If no body text exists, Gemini synthesises a summary from the
      structured fields (donor, geography, sector, eligibility, etc.).

    Returns the generated summary string, or falls back to the original
    body text if the API call fails.
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

    for attempt in range(3):
        try:
            response = _client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            msg = str(e)
            delay = re.search(r"retryDelay.*?(\d+)s", msg)
            wait = int(delay.group(1)) + 2 if delay else 60
            print(f"    [WARN] Gemini rate limit hit, retrying in {wait}s (attempt {attempt+1}/3)...")
            time.sleep(wait)
    return description  # fall back after all retries exhausted
