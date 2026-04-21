import re, time, urllib.parse
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from openpyxl.descriptors.serialisable import KEYWORDS
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
EXCEL_FILE = os.environ["EXCEL_FILE"]
from summarizer import generate_sam_summary
from reqs import MENA_COUNTRIES, KEYWORDS, COLUMNS

MAX_PAGES = 10
MAX_WORKERS = 10  # number of reusable drivers in the pool

_MENA_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in MENA_COUNTRIES) + r")\b",
    re.IGNORECASE,
)


SECTOR_MAP = {
    "Youth Workforce Development": {
        "youth employment", "job placement", "job readiness", "neet", "work readiness",
        "early-career", "job seekers"
    },
    "Entrepreneurship / SME Development": {
        "entrepreneurship", "sme", "sme development", "msme", "startup", "startup support",
        "micro entrepreneurship", "microbusiness", "women entrepreneurship",
        "green entrepreneurship", "startup incubation", "business acceleration"
    },
    "Vocational Training / Skills": {
        "vocational training", "tvet", "skills development", "upskilling", "reskilling",
        "technical training", "blended training", "curriculum development", "employability skills"
    },
    "Green Economy": {"green jobs", "green skills", "green entrepreneurship", "circular economy"},
    "Financial Inclusion / Literacy": {"financial literacy", "financial inclusion"},
    "Digital Skills": {"digital skills"},
    "Economic Empowerment / Livelihoods": {
        "economic empowerment", "economic inclusion", "income generation", "livelihoods",
        "self employment", "gig economy", "freelance"
    },
    "Capacity Building / Systems Strengthening": {
        "capacity building", "systems strengthening", "competitiveness", "skills gaps",
        "business association", "chamber of commerce", "industry federation", "private sector development"
    },
}

def is_not_expired(deadline_str):
    if not deadline_str:
        return True
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y", "%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(str(deadline_str).strip(), fmt) >= datetime.today()
        except ValueError:
            continue
    return True

def extract_mena(text):
    found = set()
    for m in _MENA_RE.findall(text or ""):
        for c in MENA_COUNTRIES:
            if m.lower() == c.lower(): found.add(c)
    return sorted(found)

def find_keywords(text):
    lower = (text or "").lower()
    return [kw for kw in KEYWORDS if kw.lower() in lower]

def infer_sector(matched):
    kws = {k.lower() for k in matched}
    sectors = [s for s, terms in SECTOR_MAP.items() if kws & terms]
    return " | ".join(sectors) if sectors else "Workforce / Economic Development"

def parse_amount(text):
    for raw in re.findall(r'\$\s*[\d,]+(?:\.\d+)?(?:\s*(?:million|M|billion|B))?', text or "", re.IGNORECASE):
        try:
            val = float(re.sub(r"[^\d.]", "", raw.replace(",", "")))
            if "million" in raw.lower(): val *= 1_000_000
            elif "billion" in raw.lower(): val *= 1_000_000_000
            if val > 0: return val
        except ValueError:
            continue
    return ""

def parse_eligibility(text):
    patterns = [
        r'(?:eligible|eligibility)[^.]{0,200}\.',
        r'(?:open to|restricted to|available to)\s+[^.]{5,200}\.',
        r'(?:only|exclusively)\s+(?:available|open)\s+(?:to|for)\s+[^.]{5,150}\.',
        r'(?:non-?profit|NGO|INGO|government entity|private sector)[^.]{0,150}(?:eligible|may apply|can apply)[^.]*\.',
        r'applicants?\s+must\s+be[^.]{5,200}\.',
    ]
    seen, hits = set(), []
    for pat in patterns:
        for m in re.findall(pat, text or "", re.IGNORECASE):
            if m.strip() not in seen:
                seen.add(m.strip())
                hits.append(m.strip())
    return " | ".join(hits[:3])

def create_df():
    return pd.DataFrame(columns=COLUMNS)

def append_to_df(new_rows, df):
    if not new_rows: return df
    combined = pd.concat([df, pd.DataFrame(new_rows, columns=COLUMNS)], ignore_index=True)
    return combined.drop_duplicates(subset=["Opportunity ID"], keep="first")


def _make_driver():
    opts = Options()
    for arg in ["--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1920,1080",
                "--disable-blink-features=AutomationControlled",
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"]:
        opts.add_argument(arg)
    return webdriver.Chrome(options=opts)

def _safe_hrefs(driver):
    """Extract opp hrefs safely, catching stale elements."""
    hrefs = []
    for el in driver.find_elements(By.CSS_SELECTOR, "a[href*='/opp/']"):
        try:
            href = el.get_attribute("href")
            if href and "/opp/" in href: hrefs.append(href)
        except StaleElementReferenceException:
            continue
    return list(set(hrefs))

def _collect_opp_urls(driver, keyword, existing_ids):
    encoded = urllib.parse.quote(keyword)
    all_urls = []
    for page in range(1, MAX_PAGES + 1):
        url = (
            f"https://sam.gov/search/?index=_all&page={page}&pageSize=25"
            f"&sort=-modifiedDate"
            f"&sfm%5Bstatus%5D%5Bis_active%5D=true"
            f"&sfm%5Bstatus%5D%5Bis_inactive%5D=true"
            f"&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL"
            f"&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D={encoded}"
        )
        driver.get(url)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/opp/']"))
            )
        except TimeoutException:
            break
        hrefs = _safe_hrefs(driver)
        print(f"    [debug] page {page} | hrefs found: {len(hrefs)}")
        new_urls = [h for h in hrefs if (m := re.search(r"/opp/([^/]+)/", h)) and m.group(1) not in existing_ids]
        if not new_urls: break
        all_urls.extend(new_urls)
    return all_urls

def _scrape_opp(opp_url, driver):
    """Scrape one opp using a borrowed driver from the pool."""
    m = re.search(r"/opp/([^/]+)/", opp_url)
    if not m: return None
    opp_id = m.group(1)
    try:
        driver.get(opp_url)
        # Wait until Angular has rendered actual content (body text > 1000 chars)
        WebDriverWait(driver, 20).until(
            lambda d: len(d.find_element(By.TAG_NAME, "body").text) > 5000
        )

        def txt(css):
            try: return driver.find_element(By.CSS_SELECTOR, css).text.strip()
            except: return ""

        body = driver.find_element(By.TAG_NAME, "body").text

        opp_type = txt("[class*='notice-type'], [class*='opportunity-type'], [class*='noticeType'], .type-label")
        allowed = {"solicitation", "presolicitation", "sources sought", "special notice", "grant", "cooperative agreement"}
        if opp_type and not any(a in opp_type.lower() for a in allowed):
            print(f"    [filtered] opp_type='{opp_type}' | {opp_id}")
            return None
        mena = extract_mena(body)
        if not mena:
            print(f"    [filtered] no MENA | opp_type='{opp_type}' | body[:300]: {body[:300]!r}")
            return None
        matched = find_keywords(body)
        if not matched:
            print(f"    [filtered] no keywords | mena={mena} | {opp_id}")
            return None
        external = []
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='http']"):
            try:
                href = a.get_attribute("href")
                if href and "sam.gov" not in href: external.append(href)
            except StaleElementReferenceException:
                continue

        # Extract fields for AI summary
        title = txt("h1, [class*='opportunity-title'], [class*='opp-title']")
        donor = txt("[class*='organization'], [class*='agency-name'], [class*='dept']")
        deadline = txt("[class*='deadline'], [class*='response-date'], [class*='responseDeadline'], .response-deadline")
        amt_max = parse_amount(txt("[class*='award-amount'], [class*='amount']"))
        eligibility = parse_eligibility(body)
        sector = infer_sector(matched)

        return {
            "Opportunity ID":       opp_id,
            "Opportunity Type":     opp_type,
            "Title":                title,
            "Donor Name":           donor,
            "Geographic Area":      ", ".join(mena),
            "Focus / Sector":       sector,
            "Application Deadline": deadline,
            "Amount Min (USD)":     "",
            "Amount Max (USD)":     str(amt_max) if amt_max else "",
            "Eligibility":          eligibility,
            "Matched Keywords":     " | ".join(matched),
            "Source Link":          opp_url,
            "Original Link":        external[0] if external else "",
            "Date Posted":          txt("[class*='posted-date'], [class*='postDate']"),
            # Placeholder for AI summary - will be generated in batch after filtering
            "AI Summary":           None,
            # Store raw data for AI summary generation
            "_opp_data":            {
                "Title": title,
                "Donor Name": donor,
                "Geographic Area": ", ".join(mena),
                "Focus / Sector": sector,
                "Eligibility": eligibility,
                "Amount Max (USD)": str(amt_max) if amt_max else "",
                "Application Deadline": deadline,
            },
        }
    except Exception as exc:
        print(f"    Error on {opp_url}: {exc}")
        return None

def _worker(opp_url, driver_pool):
    driver = driver_pool.get()
    try:
        return _scrape_opp(opp_url, driver)
    finally:
        driver_pool.put(driver)

def scrape_keyword(keyword, existing_ids, nav_driver, driver_pool):
    opp_urls = _collect_opp_urls(nav_driver, keyword, existing_ids)
    if not opp_urls: return []
    rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_worker, url, driver_pool): url for url in opp_urls}
        for future in as_completed(futures):
            row = future.result()
            if row:
                rows.append(row)
                existing_ids.add(row["Opportunity ID"])
    return rows

def main():
    df, existing_ids = create_df(), set()
    nav_driver = _make_driver()
    driver_pool = Queue()
    workers = [_make_driver() for _ in range(MAX_WORKERS)]
    for d in workers:
        driver_pool.put(d)
    try:
        for i, keyword in enumerate(KEYWORDS, 1):
            print(f"[{i:3}/{len(KEYWORDS)}] '{keyword}'", flush=True)
            new_rows = scrape_keyword(keyword, existing_ids, nav_driver, driver_pool)
            print(f"        → {len(new_rows)} new")
            df = append_to_df(new_rows, df)
    finally:
        nav_driver.quit()
        for d in workers:
            d.quit()

    # Generate AI summaries in batch for all filtered results
    print(f"\nGenerating AI summaries for {len(df)} opportunities...")
    for idx, row in df.iterrows():
        if row.get("_opp_data"):
            df.at[idx, "AI Summary"] = generate_sam_summary(row["_opp_data"])
    # Drop the temporary _opp_data column
    df = df.drop(columns=["_opp_data"])

    print(f"\nDone. Total opportunities: {len(df)}")
    
    # ── Filter expired deadlines ──────────────────────────────
    df = df[df["Application Deadline"].apply(is_not_expired)]
    print(f"After deadline filter: {len(df)} remaining.")
    # ─────────────────────────────────────────────────────────
    
    print(df)

    SHEET_NAME = "sam"

    if os.path.exists(EXCEL_FILE):
        existing_sheets = pd.ExcelFile(EXCEL_FILE).sheet_names

        if SHEET_NAME in existing_sheets:
            existing_df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
            existing_links = set(existing_df["Opportunity ID"])
            new_rows = df[~df["Opportunity ID"].isin(existing_links)]

            if not new_rows.empty:
                with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
                    startrow = writer.book[SHEET_NAME].max_row
                    new_rows.to_excel(writer, sheet_name=SHEET_NAME, startrow=startrow, index=False, header=False)
                print(f"Added {len(new_rows)} new grants")
            else:
                print("No new grants")

        else:
            # File exists but sheet doesn't — add new sheet without touching others
            with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a") as writer:
                df.to_excel(writer, sheet_name=SHEET_NAME, index=False)
            print(f"Created new sheet '{SHEET_NAME}'")

    else:
        # File doesn't exist at all — create it
        df.to_excel(EXCEL_FILE, sheet_name=SHEET_NAME, index=False)
        print("Created new Excel file")

    return df

if __name__ == "__main__":
    main()