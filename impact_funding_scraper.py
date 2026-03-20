#!/usr/bin/env python3
"""
ai_summary.py
Generates AI summaries for grant entries using Google Gemini.
Requires GEMINI_API_KEY in a .env file or environment variable.
"""

# Current Issues: sam is too slow, simpler is not working, rate limits and quotas are being exceeded
# Fixes: might need to buy better tier or switch 

import os
import re
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# IMPACT FUNDING 
def generate_summary(grant: dict) -> str:
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
            response = client.models.generate_content(
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
    return description 


# SIMPLER GRANTS 

def generate_simpler_summary(text):
    if not text or len(text.strip()) < 50:
        return ""

    prompt = f"""

Summarize this grant opportunity in one concise sentence.
Focus on the goal of the grant and the target beneficiaries.

Grant description:
{text}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        if response and response.text:
            return response.text.strip()
        else:
            return ""

    except Exception as e:
        print("AI summary error:", e)
        return ""




# DARPE 

def generate_darpe_summary(text):

    if not text or len(text.strip()) < 50:
        return ""

    prompt = f"""
Summarize this grant or tender opportunity in one concise sentence.
Focus on the goal of the funding and the target beneficiaries.

Text:
{text}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        if response and response.text:
            return response.text.strip()

        return ""

    except Exception as e:
        print("AI summary error:", e)
        return ""
    

# SAM.GOV (SLOW)
def generate_sam_summary(opportunity: dict) -> str:
    """
    Generate a concise AI summary for a SAM opportunity.

    Uses the opportunity's body text if available, otherwise falls back
    on structured fields (title, donor, sector, eligibility, geography, etc.)
    """
    body_text = opportunity.get("body", "").strip()

    structured_text = (
        f"Title: {opportunity.get('Title', '')}\n"
        f"Donor: {opportunity.get('Donor Name', '')}\n"
        f"Geography: {opportunity.get('Geographic Area', '')}\n"
        f"Sector: {opportunity.get('Focus / Sector', '')}\n"
        f"Eligibility: {opportunity.get('Eligibility', '')}\n"
        f"Amount: {opportunity.get('Amount Max (USD)', '')}\n"
        f"Deadline: {opportunity.get('Application Deadline', '')}"
    )

    text_to_summarize = body_text if body_text else structured_text

    if not text_to_summarize or len(text_to_summarize) < 50:
        return ""

    prompt = f"""
Summarize this SAM.gov grant/tender opportunity in 2-3 concise sentences.
Focus on who can apply, what is funded, and the geographic scope.

Text:
{text_to_summarize}
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            msg = str(e)
            delay = re.search(r"retryDelay.*?(\d+)s", msg)
            wait = int(delay.group(1)) + 2 if delay else 60
            print(f"    [WARN] Gemini rate limit hit, retrying in {wait}s (attempt {attempt+1}/3)...")
            time.sleep(wait)

    return text_to_summarize
