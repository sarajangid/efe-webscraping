"""
SAM.gov Opportunity Scraper
════════════════════════════════════════════════════════════════
Filters:  Workforce / economic-development keywords
          MENA region only (Morocco, Algeria, Tunisia, Egypt,
          Jordan, Palestine, Yemen, UAE, Saudi Arabia, Lebanon,
          Bahrain, Syria)
          Opportunity type: Grants + Tenders (Solicitations) only

Columns:  Opportunity ID, Opportunity Type, Title, Donor Name,
          Geographic Area, Focus/Sector, Application Deadline,
          Amount Min/Max (USD), Eligibility, Matched Keywords,
          Source Link, Original Link, Date Posted, Date Scraped

Mode:     API-first (fast & reliable).  Falls back to Selenium
          when no API key is provided.

Get a FREE SAM.gov API key at:
  https://sam.gov/profile/details  →  Register → Get API Key
Then run:  export SAM_API_KEY="your_key_here"
════════════════════════════════════════════════════════════════
"""

import os
import re
import time
import urllib.parse
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ── Optional Selenium import (only needed when no API key) ──────────────────
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Set via environment variable:  export SAM_API_KEY="your_key_here"
# Without a key you get ~30 req/hr (DEMO_KEY).  A real key gives 1000 req/hr.
SAM_API_KEY = os.getenv("SAM_API_KEY", "DEMO_KEY")

# Output is stored in-memory as DataFrame (no file persistence)

# SAM.gov API – max results per keyword (API hard-cap is 1000 per query)
MAX_API_RESULTS_PER_KEYWORD = 1000

# Selenium fallback – how many search-result pages to visit per keyword
MAX_SELENIUM_PAGES = 30


# ── MENA scope ──────────────────────────────────────────────────────────────
MENA_COUNTRIES = [
    "Morocco", "Algeria", "Tunisia", "Egypt", "Jordan",
    "Palestine", "Palestinian", "West Bank", "Gaza",
    "Yemen", "UAE", "United Arab Emirates",
    "Saudi Arabia", "Lebanon", "Bahrain", "Syria",
    # Regional terms also accepted
    "MENA", "Middle East", "North Africa", "Arab World",
    "GCC", "Maghreb", "Levant",
]
_MENA_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in MENA_COUNTRIES) + r")\b",
    re.IGNORECASE,
)


# ── Opportunity-type filter ─────────────────────────────────────────────────
# SAM.gov ptype codes:
#   o = Solicitation (TENDER)          p = Presolicitation (TENDER)
#   k = Sources Sought (TENDER-like)   s = Special Notice
#   a = Award Notice                   r = Pre-Solicitation
#   g = Sale of Surplus Property       i = Intent to Bundle
#   j/u = Justification variants       m = Modification/Amendment
#
# NOTE: True "Grants" live on Grants.gov, not SAM.gov.
#       SAM.gov primarily lists contracts/tenders.  We include
#       solicitation-family types here.  For grants, add Grants.gov
#       as a separate platform later.
TENDER_PTYPES = {"o", "p", "k", "s"}   # solicitation family  → TENDERS
ALLOWED_PTYPES = TENDER_PTYPES          # extend with grant codes if needed

PTYPE_LABELS = {
    "o": "Solicitation",
    "p": "Presolicitation",
    "k": "Sources Sought",
    "s": "Special Notice",
    "a": "Award Notice",
    "g": "Sale of Surplus Property",
    "i": "Intent to Bundle",
    "j": "Justification",
    "m": "Modification/Amendment",
    "r": "Pre-Solicitation",
    "u": "Justification and Approval",
}


# ── Keywords ────────────────────────────────────────────────────────────────
KEYWORDS = [
    # Youth Employment & Workforce Development
    "youth employment", "workforce development", "employability", "job placement",
    "job creation", "livelihoods", "economic empowerment", "economic inclusion",
    "apprenticeship", "internship", "mentorship", "job readiness", "job search",
    "labor market activation", "economic participation", "labor market entry",
    "NEET", "work readiness", "job seekers", "early-career",
    "reducing inequalities",
    # Skills and Training
    "skills development", "vocational training", "technical training", "soft skills",
    "digital skills", "green jobs", "green skills", "TVET", "upskilling", "reskilling",
    "employability skills", "curriculum development", "financial literacy",
    "circular economy", "life skills", "entrepreneurial skills", "blended training",
    # Entrepreneurship and Private Sector
    "entrepreneurship", "SME development", "private sector development",
    "self employment", "income generation", "startup incubation",
    "employer engagement", "business acceleration", "micro entrepreneurship",
    "SME", "green entrepreneurship", "women entrepreneurship", "startup support",
    "financial inclusion", "MSME", "microbusiness", "freelance", "gig economy",
    # Systems Change
    "capacity building", "systems strengthening", "competitiveness", "skills gaps",
    "business association", "chamber of commerce", "industry federation",
]


# ── Output columns ──────────────────────────────────────────────────────────
EXCEL_COLUMNS = [
    "Opportunity ID",
    "Opportunity Type",
    "Title",
    "Donor Name",
    "Geographic Area",
    "Focus / Sector",
    "Application Deadline",
    "Amount Min (USD)",
    "Amount Max (USD)",
    "Eligibility",
    "Matched Keywords",
    "Source Link",      # Link to where the scraper found the opportunity
    "Original Link",    # Link to the original issuer's page (if different)
    "Date Posted",
    "Date Scraped",
]


# ═══════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def strip_html(html_text: str) -> str:
    """Remove HTML tags and normalise whitespace."""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()


def extract_mena_countries(text: str) -> list[str]:
    """Return deduplicated list of MENA country/region names found in text."""
    if not text:
        return []
    raw_matches = _MENA_RE.findall(text)
    # Normalise capitalisation to the canonical name
    found = set()
    for m in raw_matches:
        for canonical in MENA_COUNTRIES:
            if m.lower() == canonical.lower():
                found.add(canonical)
                break
    return sorted(found)


def find_matched_keywords(text: str) -> list[str]:
    """Return which KEYWORDS appear in text (case-insensitive)."""
    if not text:
        return []
    lower = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in lower]


def infer_sector(matched_keywords: list[str]) -> str:
    """Map matched keywords to a Focus/Sector label."""
    kws = {k.lower() for k in matched_keywords}
    sectors = []

    if kws & {"youth employment", "job placement", "job readiness", "neet",
               "work readiness", "early-career", "job seekers"}:
        sectors.append("Youth Workforce Development")

    if kws & {"entrepreneurship", "sme", "sme development", "msme", "startup",
               "startup support", "micro entrepreneurship", "microbusiness",
               "new business creation", "women entrepreneurship", "green entrepreneurship",
               "startup incubation", "business acceleration"}:
        sectors.append("Entrepreneurship / SME Development")

    if kws & {"vocational training", "tvet", "skills development", "upskilling",
               "reskilling", "technical training", "blended training",
               "curriculum development", "employability skills"}:
        sectors.append("Vocational Training / Skills")

    if kws & {"green jobs", "green skills", "green entrepreneurship",
               "circular economy", "climate change"}:
        sectors.append("Green Economy")

    if kws & {"financial literacy", "financial inclusion"}:
        sectors.append("Financial Inclusion / Literacy")

    if kws & {"digital skills"}:
        sectors.append("Digital Skills")

    if kws & {"economic empowerment", "economic inclusion", "income generation",
               "livelihoods", "self employment", "gig economy", "freelance"}:
        sectors.append("Economic Empowerment / Livelihoods")

    if kws & {"capacity building", "systems strengthening", "competitiveness",
               "skills gaps", "business association", "chamber of commerce",
               "industry federation", "private sector development"}:
        sectors.append("Capacity Building / Systems Strengthening")

    return " | ".join(sectors) if sectors else "Workforce / Economic Development"


def parse_amounts(opp_data: dict, description: str) -> tuple:
    """
    Return (amount_min, amount_max) as floats or empty strings.
    Checks the API award field first, then scans description text.
    """
    amount_min, amount_max = "", ""

    # Check award field
    award = opp_data.get("award") or {}
    if award.get("amount"):
        try:
            val = float(str(award["amount"]).replace(",", "").replace("$", ""))
            amount_max = val
        except (ValueError, TypeError):
            pass

    # Scan description for dollar figures
    if not amount_max and description:
        amounts_found = re.findall(
            r'\$\s*[\d,]+(?:\.\d+)?(?:\s*(?:million|M|billion|B))?',
            description, re.IGNORECASE
        )
        for raw in amounts_found:
            try:
                clean = re.sub(r"[^\d.]", "", raw.replace(",", ""))
                val = float(clean)
                if "million" in raw.lower():
                    val *= 1_000_000
                elif "billion" in raw.lower():
                    val *= 1_000_000_000
                if val > 0:
                    amount_max = val
                    break
            except ValueError:
                continue

    return amount_min, amount_max


def parse_eligibility(description: str) -> str:
    """Extract eligibility sentences from the description."""
    if not description:
        return ""
    patterns = [
        r'(?:eligible|eligibility)[^.]{0,200}\.',
        r'(?:open to|restricted to|available to)\s+[^.]{5,200}\.',
        r'(?:only|exclusively)\s+(?:available|open)\s+(?:to|for)\s+[^.]{5,150}\.',
        r'(?:non-?profit|NGO|INGO|government entity|private sector)[^.]{0,150}'
        r'(?:eligible|may apply|can apply)[^.]*\.',
        r'applicants?\s+must\s+be[^.]{5,200}\.',
    ]
    hits = []
    for pat in patterns:
        matches = re.findall(pat, description, re.IGNORECASE)
        hits.extend(m.strip() for m in matches)
    # Deduplicate and cap at 3 sentences
    seen, unique = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return " | ".join(unique[:3])


def fmt_date(raw: str) -> str:
    """Parse ISO date string → YYYY-MM-DD, or return first 10 chars."""
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return str(raw)[:10]


# ═══════════════════════════════════════════════════════════════════════════
#  DATA FRAME I/O (in-memory)
# ═══════════════════════════════════════════════════════════════════════════

def create_empty_dataframe() -> pd.DataFrame:
    """Return an empty DataFrame with the required columns."""
    return pd.DataFrame(columns=EXCEL_COLUMNS)


def add_rows_to_dataframe(new_rows: list[dict], existing_df: pd.DataFrame) -> pd.DataFrame:
    """Append new_rows to existing_df and deduplicate."""
    if not new_rows:
        return existing_df
    new_df = pd.DataFrame(new_rows, columns=EXCEL_COLUMNS)
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Opportunity ID"], keep="first")
    return combined


def dataframe_to_csv(df: pd.DataFrame, filename: str = "output.csv") -> str:
    """
    Convert any DataFrame to a CSV file.

    Args:
        df: The pandas DataFrame to export
        filename: Output filename (default: "output.csv")

    Returns:
        The path to the saved CSV file
    """
    df.to_csv(filename, index=False)
    print(f"Saved {len(df)} rows to {filename}")
    return filename


# ═══════════════════════════════════════════════════════════════════════════
#  SAM.GOV API  (primary mode)
# ═══════════════════════════════════════════════════════════════════════════

def _sam_api_get(keyword: str, offset: int = 0, limit: int = 100) -> dict | None:
    """
    Hit the SAM.gov Opportunities v2 search endpoint.
    Handles rate-limit (429) by waiting and retrying once.
    """
    url = "https://api.sam.gov/opportunities/v2/search"
    params = {
        "api_key": SAM_API_KEY,
        "keyword": keyword,
        "limit": limit,
        "offset": offset,
        "is_active": "true",
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            print("  [rate-limited] waiting 60 s …")
            time.sleep(60)
            resp = requests.get(url, params=params, timeout=30)
            return resp.json() if resp.status_code == 200 else None
        print(f"  API error {resp.status_code}: {resp.text[:120]}")
        return None
    except requests.RequestException as exc:
        print(f"  Request error: {exc}")
        return None


def _build_row_from_api(opp: dict, existing_ids: set) -> dict | None:
    """
    Convert one SAM API opportunity dict into an output row.
    Returns None if the opportunity should be skipped.
    """
    opp_id = str(opp.get("opportunityId") or opp.get("noticeId") or "")
    if not opp_id or opp_id in existing_ids:
        return None

    # ── Opportunity-type filter ────────────────────────────────────────────
    ptype = (opp.get("type") or "").lower().strip()
    if ptype not in ALLOWED_PTYPES:
        return None
    opp_type_label = PTYPE_LABELS.get(ptype, opp.get("type", "Unknown"))

    # ── Text fields ────────────────────────────────────────────────────────
    title = opp.get("title", "") or ""
    raw_desc = opp.get("description", "") or ""
    description = strip_html(raw_desc)

    # Place-of-performance country (if API returns it)
    pop = opp.get("placeOfPerformance") or {}
    pop_country = (pop.get("country") or {}).get("name", "") or ""

    full_text = " ".join([title, description, pop_country])

    # ── MENA filter ────────────────────────────────────────────────────────
    mena_found = extract_mena_countries(full_text)
    if not mena_found:
        return None

    # ── Keyword filter ─────────────────────────────────────────────────────
    matched_kws = find_matched_keywords(full_text)
    if not matched_kws:
        return None

    # ── Extract fields ─────────────────────────────────────────────────────
    donor = (
        opp.get("organizationName")
        or (opp.get("fullParentPathName") or "").split(".")[-1].strip()
        or opp.get("department", "")
        or ""
    )

    deadline = fmt_date(opp.get("responseDeadLine") or opp.get("archiveDate") or "")
    date_posted = fmt_date(opp.get("postedDate") or "")

    amount_min, amount_max = parse_amounts(opp, description)
    eligibility = parse_eligibility(description)
    sector = infer_sector(matched_kws)
    geo_area = ", ".join(mena_found)

    # Source link = the SAM.gov page for this opportunity
    source_link = f"https://sam.gov/opp/{opp_id}/view"

    # Original link = any external URL stored in the API response
    # SAM.gov sometimes stores the issuing agency's own URL here
    original_link = ""
    for field in ("uiLink", "externalLink", "resourceLinks"):
        candidate = opp.get(field) or ""
        if isinstance(candidate, list):
            candidate = candidate[0] if candidate else ""
        if candidate and "sam.gov" not in candidate:
            original_link = candidate
            break

    return {
        "Opportunity ID":   opp_id,
        "Opportunity Type": opp_type_label,
        "Title":            title,
        "Donor Name":       donor,
        "Geographic Area":  geo_area,
        "Focus / Sector":   sector,
        "Application Deadline": deadline,
        "Amount Min (USD)": amount_min,
        "Amount Max (USD)": amount_max,
        "Eligibility":      eligibility,
        "Matched Keywords": " | ".join(matched_kws),
        "Source Link":      source_link,
        "Original Link":    original_link,
        "Date Posted":      date_posted,
        "Date Scraped":     datetime.now().strftime("%Y-%m-%d"),
    }


def scrape_via_api(keyword: str, existing_ids: set) -> list[dict]:
    """Paginate through the SAM API for one keyword and return new rows."""
    rows = []
    offset = 0
    limit = 100

    while offset < MAX_API_RESULTS_PER_KEYWORD:
        data = _sam_api_get(keyword, offset=offset, limit=limit)
        if not data:
            break

        opps = data.get("opportunitiesData") or []
        total_records = data.get("totalRecords") or 0

        if not opps:
            break

        for opp in opps:
            row = _build_row_from_api(opp, existing_ids)
            if row:
                rows.append(row)
                existing_ids.add(row["Opportunity ID"])

        offset += len(opps)
        if offset >= total_records:
            break

        time.sleep(0.5)   # stay well under rate limits

    return rows


# ═══════════════════════════════════════════════════════════════════════════
#  SELENIUM FALLBACK  (used when SAM_API_KEY is not set)
# ═══════════════════════════════════════════════════════════════════════════

def _setup_driver():
    if not SELENIUM_AVAILABLE:
        raise RuntimeError("Selenium is not installed. Run: pip install selenium")
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)


def _scrape_opp_page(driver, url: str, opp_id: str) -> dict | None:
    """
    Visit a SAM.gov opportunity detail page and extract all fields.
    Returns a row dict or None if the opp doesn't pass filters.
    """
    try:
        driver.get(url)
        time.sleep(4)

        def txt(css: str) -> str:
            try:
                return driver.find_element(By.CSS_SELECTOR, css).text.strip()
            except Exception:
                return ""

        # Opportunity type
        opp_type = txt(
            "[class*='notice-type'], [class*='opportunity-type'], "
            "[class*='noticeType'], .type-label"
        )
        # Type filter: accept solicitation-family and explicitly labelled grants
        allowed_labels = {
            "solicitation", "presolicitation", "sources sought",
            "special notice", "grant", "cooperative agreement",
        }
        if opp_type and not any(a in opp_type.lower() for a in allowed_labels):
            return None

        # Full page text for filtering
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # MENA filter
        mena_found = extract_mena_countries(body_text)
        if not mena_found:
            return None

        # Keyword filter
        matched_kws = find_matched_keywords(body_text)
        if not matched_kws:
            return None

        title    = txt("h1, [class*='opportunity-title'], [class*='opp-title']")
        donor    = txt("[class*='organization'], [class*='agency-name'], [class*='dept']")
        deadline = txt(
            "[class*='deadline'], [class*='response-date'], "
            "[class*='responseDeadline'], .response-deadline"
        )
        date_posted = txt("[class*='posted-date'], [class*='postDate']")

        # Amount
        amount_text = txt("[class*='award-amount'], [class*='amount']")
        amount_min, amount_max = "", ""
        if amount_text:
            try:
                amount_max = float(re.sub(r"[^\d.]", "", amount_text))
            except ValueError:
                pass

        # External (original) links — any href not pointing to sam.gov
        all_links = driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")
        external = [
            a.get_attribute("href") for a in all_links
            if a.get_attribute("href") and "sam.gov" not in a.get_attribute("href")
        ]
        original_link = external[0] if external else ""

        eligibility = parse_eligibility(body_text)

        return {
            "Opportunity ID":   opp_id,
            "Opportunity Type": opp_type,
            "Title":            title,
            "Donor Name":       donor,
            "Geographic Area":  ", ".join(mena_found),
            "Focus / Sector":   infer_sector(matched_kws),
            "Application Deadline": deadline,
            "Amount Min (USD)": amount_min,
            "Amount Max (USD)": amount_max,
            "Eligibility":      eligibility,
            "Matched Keywords": " | ".join(matched_kws),
            "Source Link":      url,
            "Original Link":    original_link,
            "Date Posted":      date_posted,
            "Date Scraped":     datetime.now().strftime("%Y-%m-%d"),
        }

    except Exception as exc:
        print(f"    Error on {url}: {exc}")
        return None


def scrape_via_selenium(keyword: str, existing_ids: set) -> list[dict]:
    """
    Selenium fallback: search SAM.gov, collect opportunity URLs,
    then visit each detail page.
    """
    rows = []
    driver = _setup_driver()

    try:
        for page in range(1, MAX_SELENIUM_PAGES + 1):
            encoded = urllib.parse.quote(keyword)
            url = (
                f"https://sam.gov/search/?index=opp&page={page}&pageSize=25"
                f"&sort=-modifiedDate"
                f"&sfm%5Bstatus%5D%5Bis_active%5D=true"
                f"&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bkey%5D=keyword"
                f"&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D={encoded}"
            )

            print(f"    page {page} …", end=" ", flush=True)
            driver.get(url)
            time.sleep(5)

            # Wait for at least one result card
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "a[href*='/opp/']")
                    )
                )
            except TimeoutException:
                print("no results / timeout")
                break

            # Collect unique opportunity page URLs
            link_els = driver.find_elements(By.CSS_SELECTOR, "a[href*='/opp/']")
            opp_urls = list({
                el.get_attribute("href")
                for el in link_els
                if "/opp/" in (el.get_attribute("href") or "")
            })

            if not opp_urls:
                print("no opportunity links found")
                break

            print(f"{len(opp_urls)} opportunities")

            for opp_url in opp_urls:
                match = re.search(r"/opp/([^/]+)/", opp_url)
                if not match:
                    continue
                opp_id = match.group(1)

                if opp_id in existing_ids:
                    continue

                row = _scrape_opp_page(driver, opp_url, opp_id)
                if row:
                    rows.append(row)
                    existing_ids.add(opp_id)

                time.sleep(1.5)

            time.sleep(3)

    finally:
        driver.quit()

    return rows


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("═" * 65)
    print("  SAM.gov Opportunity Scraper")
    print("  Filters : MENA region | Grants & Tenders | Workforce keywords")
    print("═" * 65)

    existing_df  = create_empty_dataframe()
    existing_ids = set()

    use_api = SAM_API_KEY and SAM_API_KEY != "DEMO_KEY"
    if use_api:
        print(f"\nMode : SAM.gov REST API  (key: …{SAM_API_KEY[-6:]})")
    else:
        print("\nMode : Selenium  (no API key set — slower, may be blocked)")
        print("Tip  : set SAM_API_KEY env var for faster results")

    print("Output : In-memory DataFrame (no file persistence)")
    print(f"Keywords to search : {len(KEYWORDS)}\n")

    total_keywords = len(KEYWORDS)
    all_new_rows: list[dict] = []

    for i, keyword in enumerate(KEYWORDS, 1):
        print(f"[{i:3}/{total_keywords}]  '{keyword}'", flush=True)

        if use_api:
            new_rows = scrape_via_api(keyword, existing_ids)
        else:
            new_rows = scrape_via_selenium(keyword, existing_ids)

        status = f"→ {len(new_rows)} new MENA opportunity/ies"
        print(f"          {status}")
        all_new_rows.extend(new_rows)

        # Update DataFrame after every keyword
        if new_rows:
            existing_df = add_rows_to_dataframe(new_rows, existing_df)

        time.sleep(2)  # polite pause between keywords

    # ── Final summary ──────────────────────────────────────────────────────
    print()
    print("═" * 65)
    print(f"  Done!")
    print(f"  New opportunities added  : {len(all_new_rows)}")
    print(f"  Total in DataFrame       : {len(existing_df)}")
    print("═" * 65)
    print()


if __name__ == "__main__":
    main()