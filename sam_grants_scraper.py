#!/usr/bin/env python3
"""
Scrape SAM.gov CFDA/Assistance Listings search results for 'grants' and append to Google Sheet.
Uses BeautifulSoup (bs4) for parsing. Fetches via requests; if the page is JS-rendered (no results),
uses Selenium to load the page with a browser and then parse with bs4.
"""

import json
import os
import re
import requests
import gspread
from urllib.parse import urljoin, urlencode
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://sam.gov"
SEARCH_URL = "https://sam.gov/search/"
API_BASE = "https://api.sam.gov/assistance-listings/v1"
OUTPUT_FIELDS = ["name", "geographic_area", "youth_generation", "pdfs", "brief_summary", "deadline", "link"]
# Header row labels for the Google Sheet (same order as OUTPUT_FIELDS)
SHEET_HEADERS = ["Name", "Geographic Area", "Youth Generation", "PDF", "Summary", "Deadline", "Link"]

DEFAULT_PARAMS = {
    "index": "cfda",
    "page": 1,
    "pageSize": 25,
    "sort": "-modifiedDate",
    "sfm[status][is_active]": "true",
    "sfm[simpleSearch][keywordRadio]": "ALL",
    "sfm[simpleSearch][keywordTags][0][value]": "grants",
}

def get_session():
    """Return a requests session with browser-like headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def fetch_via_api(api_key, pages=1, page_size=25):
    """Fetch assistance listings via SAM.gov API (no browser needed). Returns list of row dicts."""
    session = get_session()
    all_rows = []
    for page_num in range(pages):
        url = f"{API_BASE}/search"
        params = {
            "api_key": api_key,
            "pageSize": min(page_size, 1000),
            "pageNumber": page_num,
            "status": "Active",
        }
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("_embedded", {}).get("assistanceListings") or data.get("results") or data.get("assistanceListings") or []
        if not items: break
        rows = parse_json_listings(items)
        if rows: all_rows.extend(rows)
    return all_rows


def fetch_page(session, page=1, page_size=25, verify_ssl=True):
    """Fetch one page of SAM.gov CFDA search results (static HTML)."""
    params = {**DEFAULT_PARAMS, "page": page, "pageSize": page_size}
    url = SEARCH_URL + "?" + urlencode(params)
    resp = session.get(url, timeout=30, verify=verify_ssl)
    resp.raise_for_status()
    return resp.text


def fetch_page_selenium(page=1, page_size=25, headless=True):
    """Fetch one page using Selenium with Chrome (for JS-rendered content), return HTML."""
    params = {**DEFAULT_PARAMS, "page": page, "pageSize": page_size}
    url = SEARCH_URL + "?" + urlencode(params)
    opts = Options()
    if headless: opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    import time
    for attempt in range(2):
        driver = None
        try:
            driver = webdriver.Chrome(options=opts)
            driver.get(url)
            # Wait for results to load (either JSON in script or rendered cards)
            WebDriverWait(driver, 20).until(
                lambda d: "Assistance Listing" in d.page_source or "assistanceListings" in d.page_source or "searchResults" in d.page_source
            )
            time.sleep(3)
            return driver.page_source
        except Exception as e:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            if attempt == 1:
                raise
            time.sleep(2)
    return None


def _dig_listings_from_dict(obj):
    """Recursively find a list of listing-like dicts in nested JSON."""
    if isinstance(obj, list) and len(obj) > 0:
        first = obj[0]
        if isinstance(first, dict) and (first.get("title") or first.get("assistanceListingId") or first.get("programNumber")):
            return parse_json_listings(obj)
        for item in obj:
            out = _dig_listings_from_dict(item)
            if out:
                return out
    if isinstance(obj, dict):
        for key in ("results", "listings", "assistanceListings", "items", "hits", "data"):
            out = _dig_listings_from_dict(obj.get(key))
            if out:
                return out
        for v in obj.values():
            out = _dig_listings_from_dict(v)
            if out:
                return out
    return None


def extract_from_json_script(soup):
    """
    Try to find listing data in a JSON script tag (common in SPAs like Next.js).
    Returns list of dicts with name, geographic_area, youth_generation, pdfs, brief_summary, deadline, link or None.
    """
    for script in soup.find_all("script"):
        raw = (script.string or "").strip()
        if not raw or ("assistanceListing" not in raw and "searchResults" not in raw and "listing" not in raw):
            continue
        if not (raw.startswith("{") or raw.startswith("[")):
            continue
        try:
            data = json.loads(raw)
            out = _dig_listings_from_dict(data)
            if out:
                return out
        except (json.JSONDecodeError, TypeError):
            continue
    for script in soup.find_all("script", type=re.compile(r"application/(?:ld\+)?json")):
        try:
            data = json.loads(script.string or "")
            out = _dig_listings_from_dict(data)
            if out:
                return out
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def parse_json_listings(items):
    """Convert API-like list of listing objects to our CSV row format."""
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("title")
            or item.get("programTitle")
            or item.get("name")
            or item.get("assistanceListingTitle")
            or ""
        )
        aid = item.get("assistanceListingId") or item.get("id") or item.get("programNumber") or ""
        link = item.get("url") or item.get("link") or item.get("listingUrl")
        if not link and aid:
            link = f"{BASE_URL}/assistance/listings/{aid}" if "/" not in str(aid) else f"{BASE_URL}/assistance/listings/{aid}"
        if not link:
            link = ""
        elif not link.startswith("http"):
            link = urljoin(BASE_URL, link)
        location = ""
        org = item.get("agency") or item.get("department") or item.get("federalOrganization")
        if isinstance(org, dict):
            location = org.get("name") or org.get("title") or ""
        elif isinstance(org, str):
            location = org
        if not location and item.get("subtier"):
            st = item["subtier"]
            location = st.get("name", st.get("title", "")) if isinstance(st, dict) else str(st)
        brief_summary = (
            item.get("description")
            or item.get("summary")
            or item.get("objectives")
            or item.get("briefDescription")
            or ""
        )
        if isinstance(brief_summary, list):
            brief_summary = " ".join(str(x) for x in brief_summary)
        deadline = (
            item.get("deadline")
            or item.get("applicationDeadline")
            or item.get("lastUpdatedDate")
            or item.get("modifiedDate")
            or ""
        )
        rows.append({
            "name": name.strip(),
            "geographic_area": "",
            "youth_generation": "",
            "pdfs": "",
            "brief_summary": str(brief_summary).strip()[:500],
            "deadline": str(deadline).strip(),
            "link": link,
        })
    return rows if rows else None


def extract_from_html(soup):
    """
    Parse server-rendered HTML for listing cards/sections.
    Looks for links to assistance listings and nearby title/agency text.
    """
    rows = []
    # SAM.gov uses /workspace/assistance/fal/<uuid>/view for listing detail pages
    listing_links = soup.find_all("a", href=re.compile(r"workspace/assistance/fal/[\w-]+/view", re.I))
    if not listing_links:
        listing_links = soup.find_all("a", href=re.compile(r"assistance/listings?/[\d.]+", re.I))
    if not listing_links:
        listing_links = soup.find_all("a", href=re.compile(r"assistance.*listing|assistance/fal", re.I))
    seen_hrefs = set()
    for a in listing_links:
        href = a.get("href", "")
        if not href or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        link = urljoin(BASE_URL, href)
        if "/assistance/" not in link.lower():
            continue
        # Name: often the link text or nearest heading
        name = (a.get_text(strip=True) or "").strip()
        if not name:
            parent = a.find_parent(["h2", "h3", "h4", "div"])
            if parent:
                h = parent.find(["h2", "h3", "h4"])
                if h:
                    name = h.get_text(strip=True)
                else:
                    name = parent.get_text(strip=True)[:200]
        # Walk up from the link to find the container that has metadata (SAM.gov uses nested divs)
        card = a
        for _ in range(25):
            if not card or not hasattr(card, "get_text"):
                break
            text = card.get_text() or ""
            if "Last Updated Date" in text or "Dept / Ind Agency" in text:
                break
            card = getattr(card, "parent", None)
        geographic_area = ""
        youth_generation = ""
        pdfs = ""
        deadline = ""
        brief_summary = ""
        if card:
            text = card.get_text() or ""
            # Labels may be concatenated with values (e.g. "Last Updated DateMar 2, 2026")
            for label, key in [
                ("Dept / Ind Agency", None),
                ("Last Updated Date", "deadline"),
                ("Assistance Listing ID", None),
            ]:
                if label in text:
                    parts = text.split(label, 1)
                    if len(parts) > 1:
                        rest = parts[1].strip()
                        # Stop at next known label
                        stop_list = ["Subtier", "Type of Assistance", "Is Funded", "Dept / Ind Agency", "\n"]
                        if key == "deadline":
                            stop_list = ["Dept", "Subtier", "Is Funded", "\n"]
                        for stop in stop_list:
                            idx = rest.find(stop)
                            if idx >= 0:
                                rest = rest[:idx]
                        value = rest.strip()[:200]
                        if key == "deadline":
                            deadline = value
            # First paragraph or description as summary if present
            p = card.find("p")
            if p:
                brief_summary = p.get_text(strip=True)[:500]
            if not brief_summary:
                desc = card.find(class_=re.compile(r"description|summary|objective", re.I))
                if desc:
                    brief_summary = desc.get_text(strip=True)[:500]
        rows.append({
            "name": name[:300] if name else "Assistance Listing",
            "geographic_area": "",
            "youth_generation": "",
            "pdfs": "",
            "brief_summary": brief_summary[:500],
            "deadline": deadline[:100],
            "link": link,
        })
    return rows if rows else None


def _extract_geographic_from_text(text):
    """Extract geographic area (country/region e.g. MENA) from page text."""
    if not text:
        return ""
    text_lower = text.lower()
    # Region keywords
    if "mena" in text_lower or "middle east" in text_lower or "north africa" in text_lower:
        return "MENA"
    for region in ["sub-saharan africa", "east asia", "south asia", "latin america", "europe", "global", "worldwide", "international"]:
        if region in text_lower:
            return region.title()
    # Country names (common in eligibility)
    countries = [
        "egypt", "jordan", "lebanon", "morocco", "tunisia", "iraq", "yemen", "libya",
        "syria", "algeria", "saudi arabia", "uae", "kuwait", "bahrain", "oman", "qatar",
        "israel", "palestine", "pakistan", "afghanistan", "nigeria", "kenya", "ghana",
    ]
    found = [c.title() for c in countries if c in text_lower]
    if found:
        return ", ".join(found[:5])
    return ""


def _extract_youth_from_text(text):
    """Extract youth-generation relevance from page text (beneficiaries/description)."""
    if not text:
        return ""
    text_lower = text.lower()
    youth_phrases = [
        "youth", "young people", "young adults", "ages 18", "ages 15", "ages 16",
        "adolescent", "students", "next generation", "young leaders", "youth-led",
        "gen z", "millennial", "under 30", "under 35", "young professionals",
    ]
    found = [p for p in youth_phrases if p in text_lower]
    if found:
        return "Yes"
    return ""


def scrape_listing_detail(detail_url, driver=None, base_url=BASE_URL):
    """
    Fetch one listing detail page and extract geographic_area, youth_generation, pdfs, brief_summary.
    Returns dict with those keys (and deadline if found on page). Uses existing driver if provided.
    """
    import time
    result = {"geographic_area": "", "youth_generation": "", "pdfs": "", "brief_summary": "", "deadline": ""}
    if not detail_url:
        return result
    own_driver = False
    if driver is None:
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=opts)
        own_driver = True
    try:
        driver.get(detail_url)
        time.sleep(3)
        html = driver.page_source
    finally:
        if own_driver and driver:
            try:
                driver.quit()
            except Exception:
                pass
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(separator=" ", strip=True)
    result["geographic_area"] = _extract_geographic_from_text(full_text)[:300]
    result["youth_generation"] = _extract_youth_from_text(full_text)
    # PDF links
    pdf_links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if ".pdf" in href.lower() or "pdf" in (a.get_text() or "").lower():
            url = urljoin(base_url, href)
            if url not in pdf_links:
                pdf_links.append(url)
    result["pdfs"] = " | ".join(pdf_links[:10])
    # Brief summary: objectives or first long paragraph
    for label in ["Objectives", "Objective", "Description", "Summary", "Program Description"]:
        el = soup.find(string=re.compile(re.escape(label), re.I))
        if el:
            parent = el.parent
            for _ in range(5):
                if not parent:
                    break
                if parent.name in ("div", "section", "p"):
                    t = parent.get_text(separator=" ", strip=True)
                    if len(t) > 80:
                        result["brief_summary"] = t[:800]
                        break
                parent = getattr(parent, "parent", None)
            if result["brief_summary"]:
                break
    if not result["brief_summary"] and full_text:
        result["brief_summary"] = full_text[:800]
    # Deadline on detail page (e.g. "Application Deadline: March 15, 2026")
    deadline_match = re.search(r"(?:application\s+)?deadline\s*[:\-]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", full_text, re.I)
    if deadline_match:
        result["deadline"] = deadline_match.group(1).strip()[:50]
    return result


def scrape_page(html, base_url=BASE_URL):
    """Extract listing rows from one page HTML. Prefer JSON embed, fallback to HTML."""
    soup = BeautifulSoup(html, "html.parser")
    rows = extract_from_json_script(soup)
    if rows:
        return rows
    return extract_from_html(soup) or []


def _ensure_row_fields(row):
    """Ensure each row has all OUTPUT_FIELDS; fill missing with empty string."""
    for f in OUTPUT_FIELDS:
        if f not in row:
            row[f] = ""
    return row


def scrape_sam_grants(pages=1, page_size=25, verify_ssl=True, use_selenium=False, api_key=None, scrape_details=True, max_details=None):
    """Scrape SAM.gov grants search results; optionally scrape each listing detail page for geographic_area, youth, pdfs, brief_summary."""
    if api_key:
        rows = fetch_via_api(api_key, pages=pages, page_size=page_size)
    else:
        all_rows = []
        if use_selenium:
            for page in range(1, pages + 1):
                html = fetch_page_selenium(page=page, page_size=page_size)
                rows = scrape_page(html)
                if not rows:
                    break
                all_rows.extend(rows)
            rows = all_rows
        else:
            session = get_session()
            for page in range(1, pages + 1):
                html = fetch_page(session, page=page, page_size=page_size, verify_ssl=verify_ssl)
                page_rows = scrape_page(html)
                if not page_rows:
                    break
                all_rows.extend(page_rows)
            rows = all_rows
    for r in rows:
        _ensure_row_fields(r)
    if not scrape_details or not rows:
        return rows
    import time
    n = len(rows) if max_details is None else min(max_details, len(rows))
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=opts)
    try:
        for i, row in enumerate(rows):
            if i >= n:
                break
            link = row.get("link")
            if not link:
                continue
            try:
                detail = scrape_listing_detail(link, driver=driver)
                row["geographic_area"] = detail.get("geographic_area") or row.get("geographic_area", "")
                row["youth_generation"] = detail.get("youth_generation") or row.get("youth_generation", "")
                row["pdfs"] = detail.get("pdfs") or row.get("pdfs", "")
                if detail.get("brief_summary"):
                    row["brief_summary"] = detail["brief_summary"][:800]
                if detail.get("deadline"):
                    row["deadline"] = detail["deadline"]
            except Exception:
                pass
            time.sleep(1)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return rows


def _spreadsheet_id_from_url(url_or_id):
    """Extract spreadsheet ID from a Google Sheets URL or return as-is if already an ID."""
    s = (url_or_id or "").strip()
    if not s:
        return None
    # URL form: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit?...
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    return s if re.match(r"^[a-zA-Z0-9_-]+$", s) else None


def append_to_google_sheet(rows, spreadsheet_id, credentials_path=None, sheet_index=0):
    """
    Append only new scraped rows to a Google Sheet (deduplicated by link).
    Uses the first worksheet by default. If the sheet is empty, writes headers then data.
    Requires gspread and google-auth. Auth via service account JSON.
    Returns the number of rows appended (0 if all were already in the sheet).
    """
    if not rows:
        return 0
    spreadsheet_id = _spreadsheet_id_from_url(spreadsheet_id)
    if not spreadsheet_id:
        raise ValueError("Invalid spreadsheet ID or URL")
    if credentials_path:
        gc = gspread.service_account(filename=credentials_path)
    else:
        gc = gspread.service_account()
    sh = gc.open_by_key(spreadsheet_id)
    wks = sh.get_worksheet(sheet_index)
    existing = wks.get_all_values()
    # Deduplicate by "link" (unique per listing)
    def norm_link(s):
        return (s or "").strip().rstrip("/")
    link_col_idx = OUTPUT_FIELDS.index("link")
    if existing and len(existing) > 1:
        header = existing[0]
        link_col = link_col_idx
        # Match "Link" column case-insensitively (sheet may have SHEET_HEADERS)
        for i, h in enumerate(header):
            if (h or "").strip().lower() == "link":
                link_col = i
                break
        existing_links = {norm_link(str(row[link_col])) for row in existing[1:] if len(row) > link_col}
    else:
        existing_links = set()
    new_rows = [r for r in rows if norm_link(r.get("link")) and norm_link(r.get("link")) not in existing_links]
    if not new_rows:
        return 0
    data_rows = [[(r.get(k) or "") for k in OUTPUT_FIELDS] for r in new_rows]
    if not existing:
        wks.append_row(SHEET_HEADERS, value_input_option="USER_ENTERED")
    wks.append_rows(data_rows, value_input_option="USER_ENTERED")
    return len(new_rows)


# Default Google Sheet for EFE Web Scraper (append target)
DEFAULT_GOOGLE_SHEET_ID = "1uV-a5J-7FFS9tHBBhvr7lOJ0RfBKIc_fFHWn3wTfSjY"

if __name__ == "__main__":
    import argparse
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="Scrape SAM.gov grants (CFDA) search results and append to Google Sheet.")
    parser.add_argument("-p", "--pages", type=int, default=1, help="Number of result pages to scrape")
    parser.add_argument("--page-size", type=int, default=25, help="Results per page")
    parser.add_argument("--no-verify-ssl", action="store_true", help="Disable SSL verification (use if you see certificate errors)")
    parser.add_argument("--selenium", action="store_true", help="Use Selenium + Chrome to load JS-rendered page (default when no API key)")
    parser.add_argument("--no-selenium", action="store_true", help="Use only requests (will get 0 results; SAM.gov is JS-rendered)")
    parser.add_argument("--api-key", default=os.environ.get("SAM_API_KEY"), help="SAM.gov API key (or set SAM_API_KEY). Get one at https://sam.gov/profile/details")
    parser.add_argument("--no-scrape-details", action="store_true", help="Skip scraping each listing detail page (faster; geographic_area, youth, pdfs, full summary will be empty)")
    parser.add_argument("--max-details", type=int, default=None, metavar="N", help="Max number of listing detail pages to scrape (default: all)")
    parser.add_argument("--google-sheet", nargs="?", const=DEFAULT_GOOGLE_SHEET_ID, metavar="ID_OR_URL", help="Append results to this Google Sheet (ID or full URL). No value = use default EFE sheet.")
    parser.add_argument("--no-google-sheet", action="store_true", help="Do not append to Google Sheet (even if credentials are set)")
    parser.add_argument("--credentials", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"), help="Path to Google service account JSON (or set GOOGLE_APPLICATION_CREDENTIALS)")
    args = parser.parse_args()
    # Normalize credentials path (strip quotes that .env might have)
    if args.credentials:
        args.credentials = args.credentials.strip().strip("'").strip('"')
    # Default: append to sheet when credentials exist (unless --no-google-sheet)
    if args.google_sheet is None and not args.no_google_sheet and args.credentials:
        args.google_sheet = DEFAULT_GOOGLE_SHEET_ID
    verify = not args.no_verify_ssl
    # Default to Selenium when no API key so the script works with Chrome
    use_selenium = args.selenium or (not args.no_selenium and not args.api_key)
    if use_selenium:
        print("Using Selenium + Chrome to load the page...")
    print("Fetching SAM.gov search results...")
    rows = scrape_sam_grants(
        pages=args.pages,
        page_size=args.page_size,
        verify_ssl=verify,
        use_selenium=use_selenium,
        api_key=args.api_key,
        scrape_details=not args.no_scrape_details,
        max_details=args.max_details,
    )
    print(f"Scraped {len(rows)} listings.")
    if rows:
        if args.google_sheet is not None:
            if not args.credentials:
                print("Skipping Google Sheet: set GOOGLE_APPLICATION_CREDENTIALS in .env (path to service account JSON)")
            else:
                try:
                    sheet_id = _spreadsheet_id_from_url(args.google_sheet) or args.google_sheet
                    print(f"Appending to Google Sheet (ID: {sheet_id})...")
                    n_appended = append_to_google_sheet(rows, args.google_sheet, credentials_path=args.credentials)
                    if n_appended:
                        print(f"Appended {n_appended} new row(s) to Google Sheet (skipped {len(rows) - n_appended} already present).")
                    else:
                        print(f"All {len(rows)} row(s) already in sheet; nothing to append.")
                except Exception as e:
                    import traceback
                    print(f"Google Sheet append failed: {e}")
                    traceback.print_exc()
                    err_str = str(e).lower()
                    if "403" in str(e) or "has not been used" in err_str or "is disabled" in err_str:
                        print("  Fix: Enable the Google Sheets API for your project:")
                        print("  https://console.cloud.google.com/apis/library/sheets.googleapis.com")
                    elif "credentials" in err_str or "auth" in err_str or "permission" in err_str:
                        print("  Tip: Share the sheet with your service account email (Editor) and ensure GOOGLE_APPLICATION_CREDENTIALS points to the JSON key path.")
    else:
        if not use_selenium:
            print("No listings found. SAM.gov loads results via JavaScript. Run without --no-selenium to use Chrome.")
        else:
            print("No listings found. Try with an API key: https://open.gsa.gov/api/assistance-listings-api/")
