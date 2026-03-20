#!/usr/bin/env python3
"""
Scraper for fundsforngos.org grant listings.
Saves all grants found across the configured listing URLs.

Output: grants.csv and grants.json
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import logging
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

LISTING_URLS = [
    'https://www2.fundsforngos.org/tag/lebanon/',
    'https://www2.fundsforngos.org/category/education/',
    'https://www2.fundsforngos.org/category/economic-development/',
    'https://www2.fundsforngos.org/category/employment-labor/',
    'https://fundsforcompanies.fundsforngos.org/area/latest-grants-and-resources-for-education/',
    'https://fundsforindividuals.fundsforngos.org/type_of_individuals/students/',
]

# Grants must mention at least one of these countries somewhere on their page.
# The Lebanon tag URL is exempt — all grants there are already Lebanon-relevant.
TARGET_COUNTRIES = [
    'Morocco', 'Algeria', 'Tunisia', 'Egypt', 'Jordan', 'Palestine',
    'Yemen', 'UAE', 'United Arab Emirates', 'Saudi Arabia', 'Lebanon',
    'Bahrain',
]

LEBANON_TAG_URL = 'https://www2.fundsforngos.org/tag/lebanon/'

# Max pages per listing URL (set to None to scrape all pages)
# Note: some categories have 200+ pages; lower this for quick tests
MAX_PAGES = None

REQUEST_DELAY = 1.5  # seconds between requests

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
}

# ── HTTP helpers ─────────────────────────────────────────────────────────────

def get_soup(url, session, retries=3):
    """Fetch a URL and return a BeautifulSoup object, with retries."""
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            logger.debug(f"  HTTP {resp.status_code} | {len(resp.text)} chars | final URL: {resp.url}")
            return BeautifulSoup(resp.text, 'html.parser')
        except Exception as exc:
            logger.warning(f"Attempt {attempt + 1}/{retries} failed for {url}: {exc}")
            if attempt < retries - 1:
                time.sleep(REQUEST_DELAY * (attempt + 2))
    logger.error(f"Giving up on {url}")
    return None


# ── Listing page scraping ────────────────────────────────────────────────────

# URL path segments that identify listing/navigation pages rather than grant pages
LISTING_PATH_SEGMENTS = (
    '/category/', '/tag/', '/page/', '/area/', '/type_of_individuals/',
    '/author/', '/feed/', '/wp-', '?', '#',
)


def resolve_url(href, base_url):
    """Turn a relative href into an absolute URL using the base page's origin."""
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        # e.g. base_url = https://fundsforindividuals.fundsforngos.org/...
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return None


def is_grant_link(url, base_url):
    """
    Return True if the URL looks like an individual grant page on the same site.
    - Same host as the listing page
    - Path has at least two segments: /category/slug/
    - Not a listing/navigation URL
    """
    from urllib.parse import urlparse
    try:
        listing_host = urlparse(base_url).netloc
        grant_host = urlparse(url).netloc
        if listing_host != grant_host:
            return False
        path = urlparse(url).path
        # Must have at least /segment/slug structure
        parts = [p for p in path.strip('/').split('/') if p]
        if len(parts) < 2:
            return False
        if any(seg in url for seg in LISTING_PATH_SEGMENTS):
            return False
        return True
    except Exception:
        return False


def extract_links_from_listing(soup, base_url):
    """
    Pull individual grant page URLs from a listing page.
    Works across all three subdomains by collecting every anchor and filtering
    by URL shape rather than relying on specific HTML structure.
    """
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        absolute = resolve_url(href, base_url)
        if absolute and is_grant_link(absolute, base_url):
            links.add(absolute)
    return links


def get_next_page_url(soup, base_url):
    """Return the URL of the next listing page, or None if on the last page."""
    # rel="next" is most reliable
    nxt = soup.find('a', rel=lambda r: r and 'next' in r)
    if nxt and nxt.get('href'):
        return resolve_url(nxt['href'].strip(), base_url)

    # Text / aria-label patterns
    for a in soup.find_all('a', href=True):
        text = a.get_text(strip=True)
        if re.fullmatch(r'(Next\s*Page?|next|»|›)', text, re.I):
            return resolve_url(a['href'].strip(), base_url)

    # Class-based fallback
    nxt = soup.find('a', class_=re.compile(r'\bnext\b', re.I))
    if nxt and nxt.get('href'):
        return resolve_url(nxt['href'].strip(), base_url)

    return None


def collect_all_grant_links(base_url, session):
    """
    Paginate through a listing URL and collect all grant page URLs.
    """
    all_links = set()
    current_url = base_url
    page_num = 1

    while current_url:
        logger.info(f"  Listing page {page_num}: {current_url}")
        soup = get_soup(current_url, session)
        if not soup:
            break

        page_links = extract_links_from_listing(soup, current_url)
        logger.info(f"    → {len(page_links)} grant links found")
        all_links.update(page_links)

        if MAX_PAGES and page_num >= MAX_PAGES:
            logger.info(f"    Reached MAX_PAGES={MAX_PAGES}, stopping")
            break

        current_url = get_next_page_url(soup, current_url)
        page_num += 1
        time.sleep(REQUEST_DELAY)

    return all_links

# ── Grant page extraction ────────────────────────────────────────────────────

def contains_target_country(text):
    """Return True if any target country appears in the text (case-insensitive)."""
    text_lower = text.lower()
    return any(c.lower() in text_lower for c in TARGET_COUNTRIES)


def first_regex_match(text, patterns):
    """Try each pattern in order; return the first capture group that matches."""
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            value = m.group(1).strip()
            value = re.sub(r'\s+', ' ', value)
            return value
    return ''



def extract_grant_info(grant_url, source_url, session):
    """
    Visit a grant page and return a dict of structured fields.
    Returns None if the page could not be fetched.
    """
    soup = get_soup(grant_url, session)
    if not soup:
        return None

    # ── Title ──────────────────────────────────────────────────────────────
    title = ''
    h1 = soup.find('h1')
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og = soup.find('meta', property='og:title')
        if og:
            title = og.get('content', '').strip()

    # ── Main content block ─────────────────────────────────────────────────
    content = (
        soup.find('div', class_=re.compile(r'entry-content|post-content|article-content', re.I))
        or soup.find('article')
        or soup.find('main')
        or soup.find('div', id=re.compile(r'^(content|main)$', re.I))
        or soup.body
    )
    full_text = content.get_text(separator='\n', strip=True) if content else soup.get_text('\n', strip=True)

    # ── Summary ────────────────────────────────────────────────────────────
    summary = ''
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc:
        summary = meta_desc.get('content', '').strip()
    if not summary and content:
        for p in content.find_all('p'):
            txt = p.get_text(strip=True)
            if len(txt) > 80:
                summary = txt[:600] + ('...' if len(txt) > 600 else '')
                break

    # ── Deadline ───────────────────────────────────────────────────────────
    deadline = first_regex_match(full_text, [
        r'[Dd]eadline(?:\s+[Dd]ate)?[:\-\s]+([^\n]+)',
        r'[Cc]losing\s+[Dd]ate[:\-\s]+([^\n]+)',
        r'[Aa]pplication\s+[Dd]eadline[:\-\s]+([^\n]+)',
        r'[Ss]ubmission\s+[Dd]eadline[:\-\s]+([^\n]+)',
        r'[Dd]ue\s+[Dd]ate[:\-\s]+([^\n]+)',
    ])

    # ── Geographic location ────────────────────────────────────────────────
    location = first_regex_match(full_text, [
        r'[Ee]ligible\s+[Cc]ountries[:\-\s]+([^\n]+)',
        r'[Cc]ountries?\s+[Ee]ligible[:\-\s]+([^\n]+)',
        r'[Gg]eographic\s+(?:[Ff]ocus|[Ee]ligibility|[Ss]cope)[:\-\s]+([^\n]+)',
        r'[Oo]pen\s+[Tt]o[:\-\s]+([^\n]+)',
        r'[Ww]ho\s+[Cc]an\s+[Aa]pply[:\-\s]+([^\n]+)',
        r'[Cc]ountries?\s+of\s+[Ee]ligibility[:\-\s]+([^\n]+)',
        r'[Nn]ationality\s+[Rr]equirements?[:\-\s]+([^\n]+)',
        r'[Ll]ocation[:\-\s]+([^\n]+)',
    ])

    # ── Donor name & application link ──────────────────────────────────────
    # Pages consistently end with "For more information, visit [Org Name]"
    # where the anchor text is the donor and the href is the application site.
    donor = ''
    app_link = ''
    info_visit_keywords = ('more information', 'for more info', 'visit the', 'visit ')
    apply_keywords = ('apply now', 'apply here', 'apply online', 'submit application',
                      'apply', 'application form', 'register', 'nominate', 'click here')

    for a in (content or soup).find_all('a', href=True):
        href = a['href']
        if not href.startswith('http') or 'fundsforngos.org' in href:
            continue
        a_text = a.get_text(strip=True)
        parent_text = (a.parent.get_text(strip=True).lower() if a.parent else '')
        if a_text and any(kw in parent_text for kw in info_visit_keywords):
            if not donor:
                donor = a_text
            if not app_link:
                app_link = href

    # If no "more information" link found, fall back to first apply-keyword link
    if not app_link:
        for a in (content or soup).find_all('a', href=True):
            href = a['href']
            if href.startswith('http') and 'fundsforngos.org' not in href:
                if any(kw in a.get_text(strip=True).lower() for kw in apply_keywords):
                    app_link = href
                    break

    # ── Geographic filter ──────────────────────────────────────────────────
    # Grants from the Lebanon tag are pre-filtered; all others must mention
    # at least one target country somewhere on the page.
    if source_url != LEBANON_TAG_URL and not contains_target_country(full_text):
        return None

    return {
        'title': title,
        'summary': summary,
        'donor': donor,
        'geographic_location': location,
        'deadline': deadline,
        'view_grant': 'view grant link',
        'application_link': app_link,
        'grant_page_url': grant_url,
        'source_listing_url': source_url,
    }

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    all_grants = []
    seen_urls = set()

    for listing_url in LISTING_URLS:
        logger.info(f"\n{'=' * 70}")
        logger.info(f"Listing: {listing_url}")
        logger.info(f"{'=' * 70}")

        grant_urls = collect_all_grant_links(listing_url, session)
        logger.info(f"Total grant URLs collected: {len(grant_urls)}")

        for grant_url in sorted(grant_urls):
            if grant_url in seen_urls:
                continue
            seen_urls.add(grant_url)

            logger.info(f"Visiting: {grant_url}")
            info = extract_grant_info(grant_url, listing_url, session)
            time.sleep(REQUEST_DELAY)

            if info:
                all_grants.append(info)

    if not all_grants:
        logger.warning("No grants found.")
        return

    df = pd.DataFrame(all_grants)

    df.to_csv('grants.csv', index=False)
    logger.info(f"\nSaved {len(df)} grants → grants.csv")

    with open('grants.json', 'w', encoding='utf-8') as f:
        json.dump(all_grants, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(all_grants)} grants → grants.json")

    with pd.ExcelWriter('grants.xlsx', engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Grants')
        ws = writer.sheets['Grants']
        # Auto-fit column widths
        for col in ws.columns:
            max_len = max((len(str(cell.value)) if cell.value else 0) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 80)
    logger.info(f"Saved {len(df)} grants → grants.xlsx")


if __name__ == '__main__':
    main()
