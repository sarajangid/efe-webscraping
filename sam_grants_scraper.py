import re, time, urllib.parse
from datetime import datetime
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

MAX_PAGES = 25

MENA_COUNTRIES = [
    "Morocco", "Algeria", "Tunisia", "Egypt", "Jordan",
    "Palestine", "Palestinian", "West Bank", "Gaza", "Yemen",
    "UAE", "United Arab Emirates", "Saudi Arabia", "Lebanon",
    "Bahrain", "Syria", "MENA", "Middle East", "North Africa",
    "Arab World", "GCC", "Maghreb", "Levant",
]
_MENA_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in MENA_COUNTRIES) + r")\b",
    re.IGNORECASE,
)

KEYWORDS = [
    "youth employment", "workforce development", "employability", "job placement",
    "job creation", "livelihoods", "economic empowerment", "economic inclusion",
    "apprenticeship", "internship", "mentorship", "job readiness", "job search",
    "labor market activation", "economic participation", "labor market entry",
    "NEET", "work readiness", "job seekers", "early-career", "reducing inequalities",
    "skills development", "vocational training", "technical training", "soft skills",
    "digital skills", "green jobs", "green skills", "TVET", "upskilling", "reskilling",
    "employability skills", "curriculum development", "financial literacy",
    "circular economy", "life skills", "entrepreneurial skills", "blended training",
    "entrepreneurship", "SME development", "private sector development",
    "self employment", "income generation", "startup incubation", "employer engagement",
    "business acceleration", "micro entrepreneurship", "SME", "green entrepreneurship",
    "women entrepreneurship", "startup support", "financial inclusion", "MSME",
    "microbusiness", "freelance", "gig economy", "capacity building",
    "systems strengthening", "competitiveness", "skills gaps", "business association",
    "chamber of commerce", "industry federation",
]

COLUMNS = [
    "Opportunity ID", "Opportunity Type", "Title", "Donor Name", "Geographic Area",
    "Focus / Sector", "Application Deadline", "Amount Min (USD)", "Amount Max (USD)",
    "Eligibility", "Matched Keywords", "Source Link", "Original Link",
    "Date Posted", "Date Scraped",
]

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


def extract_mena(text):
    found = set()
    for m in _MENA_RE.findall(text or ""):
        for c in MENA_COUNTRIES:
            if m.lower() == c.lower():
                found.add(c)
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


def _setup_driver():
    opts = Options()
    for arg in ["--headless", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1920,1080",
                "--disable-blink-features=AutomationControlled",
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"]:
        opts.add_argument(arg)
    return webdriver.Chrome(options=opts)

def _scrape_opp(driver, url, opp_id):
    try:
        driver.get(url)
        time.sleep(4)

        def txt(css):
            try: return driver.find_element(By.CSS_SELECTOR, css).text.strip()
            except: return ""

        opp_type = txt("[class*='notice-type'], [class*='opportunity-type'], [class*='noticeType'], .type-label")
        allowed = {"solicitation", "presolicitation", "sources sought", "special notice", "grant", "cooperative agreement"}
        if opp_type and not any(a in opp_type.lower() for a in allowed):
            return None

        body = driver.find_element(By.TAG_NAME, "body").text
        mena = extract_mena(body)
        if not mena: return None
        matched = find_keywords(body)
        if not matched: return None

        external = [
            a.get_attribute("href") for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")
            if a.get_attribute("href") and "sam.gov" not in a.get_attribute("href")
        ]
        return {
            "Opportunity ID":       opp_id,
            "Opportunity Type":     opp_type,
            "Title":                txt("h1, [class*='opportunity-title'], [class*='opp-title']"),
            "Donor Name":           txt("[class*='organization'], [class*='agency-name'], [class*='dept']"),
            "Geographic Area":      ", ".join(mena),
            "Focus / Sector":       infer_sector(matched),
            "Application Deadline": txt("[class*='deadline'], [class*='response-date'], [class*='responseDeadline'], .response-deadline"),
            "Amount Min (USD)":     "",
            "Amount Max (USD)":     parse_amount(txt("[class*='award-amount'], [class*='amount']")),
            "Eligibility":          parse_eligibility(body),
            "Matched Keywords":     " | ".join(matched),
            "Source Link":          url,
            "Original Link":        external[0] if external else "",
            "Date Posted":          txt("[class*='posted-date'], [class*='postDate']"),
            "Date Scraped":         datetime.now().strftime("%Y-%m-%d"),
        }
    except Exception as exc:
        print(f"    Error on {url}: {exc}")
        return None

def scrape_keyword(keyword, existing_ids):
    rows, driver = [], _setup_driver()
    encoded = urllib.parse.quote(keyword)
    try:
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
            time.sleep(5)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/opp/']"))
                )
            except TimeoutException:
                break

            opp_urls = list({
                el.get_attribute("href")
                for el in driver.find_elements(By.CSS_SELECTOR, "a[href*='/opp/']")
                if "/opp/" in (el.get_attribute("href") or "")
            })
            if not opp_urls: break

            for opp_url in opp_urls:
                m = re.search(r"/opp/([^/]+)/", opp_url)
                if not m or m.group(1) in existing_ids: continue
                opp_id = m.group(1)
                row = _scrape_opp(driver, opp_url, opp_id)
                if row:
                    rows.append(row)
                    existing_ids.add(opp_id)
                time.sleep(1.5)
            time.sleep(3)
    finally:
        driver.quit()
    return rows


def main():
    df, existing_ids = create_df(), set()
    for i, keyword in enumerate(KEYWORDS, 1):
        print(f"[{i:3}/{len(KEYWORDS)}] '{keyword}'", flush=True)
        new_rows = scrape_keyword(keyword, existing_ids)
        print(f"        → {len(new_rows)} new")
        df = append_to_df(new_rows, df)
        time.sleep(2)
    print(f"\nDone. Total opportunities: {len(df)}")
    return df


if __name__ == "__main__":
    main()