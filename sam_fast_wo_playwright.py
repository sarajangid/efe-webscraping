import argparse, re, urllib.parse
import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
from dotenv import load_dotenv
from summarizer import generate_sam_summary
from reqs import MENA_COUNTRIES, KEYWORDS, COLUMNS
from dev_aid_wo_playwright import norm, matches, parse_amount

load_dotenv()
EXCEL_FILE = os.environ["EXCEL_FILE"]

BASE_URL = "https://sam.gov/search/?index=_all&sort=-modifiedDate&sfm%5Bstatus%5D%5Bis_active%5D=true&sfm%5Bstatus%5D%5Bis_inactive%5D=true&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL"
SAM_BASE = "https://sam.gov"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

SECTOR_MAP = {
    "Youth Workforce Development": {"youth employment","job placement","job readiness","neet","work readiness","early-career","job seekers"},
    "Entrepreneurship / SME Development": {"entrepreneurship","sme","sme development","msme","startup","startup support","micro entrepreneurship","microbusiness","women entrepreneurship","green entrepreneurship","startup incubation","business acceleration"},
    "Vocational Training / Skills": {"vocational training","tvet","skills development","upskilling","reskilling","technical training","blended training","curriculum development","employability skills"},
    "Green Economy": {"green jobs","green skills","green entrepreneurship","circular economy"},
    "Financial Inclusion / Literacy": {"financial literacy","financial inclusion"},
    "Digital Skills": {"digital skills"},
    "Economic Empowerment / Livelihoods": {"economic empowerment","economic inclusion","income generation","livelihoods","self employment","gig economy","freelance"},
    "Capacity Building / Systems Strengthening": {"capacity building","systems strengthening","competitiveness","skills gaps","business association","chamber of commerce","industry federation","private sector development"},
}

def infer_sector(matched):
    return " | ".join(s for s, terms in SECTOR_MAP.items() if {k.lower() for k in matched} & terms) or "Workforce / Economic Development"

def parse_eligibility(text):
    patterns = [r'(?:eligible|eligibility)[^.]{0,200}\.', r'(?:open to|restricted to|available to)\s+[^.]{5,200}\.', r'(?:only|exclusively)\s+(?:available|open)\s+(?:to|for)\s+[^.]{5,150}\.', r'(?:non-?profit|NGO|INGO|government entity|private sector)[^.]{0,150}(?:eligible|may apply|can apply)[^.]*\.', r'applicants?\s+must\s+be[^.]{5,200}\.']
    seen, hits = set(), []
    [hits.append(m.strip()) or seen.add(m.strip()) for pat in patterns for m in re.findall(pat, text or "", re.IGNORECASE) if m.strip() not in seen]
    return " | ".join(hits[:3])

def get_css(soup, sel):
    el = soup.select_one(sel)
    return norm(el.get_text(separator=" ", strip=True)) if el else ""

def get_links(session, keyword, pg, existing_ids):
    url = f"{BASE_URL}&page={pg}&pageSize=25&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D={urllib.parse.quote(keyword)}"
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    raw_hrefs = list({a.get("href") for a in soup.select("a[href*='/opp/']") if a.get("href")})
    hrefs = [urllib.parse.urljoin(SAM_BASE, h) for h in raw_hrefs]
    print(f"    [debug] page {pg} | hrefs found: {len(hrefs)}")
    return [h for h in hrefs if (m := re.search(r"/opp/([^/]+)/", h)) and m.group(1) not in existing_ids]

def scrape_detail(session, opp_url):
    if not (m := re.search(r"/opp/([^/]+)/", opp_url)): return None
    opp_id = m.group(1)
    try:
        resp = session.get(opp_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        print(f"    [WARN] Request failed: {opp_url}"); return None

    soup = BeautifulSoup(resp.text, "html.parser")
    body = norm(soup.get_text(separator=" "))

    opp_type = get_css(soup, "[class*='notice-type'],[class*='opportunity-type'],[class*='noticeType'],.type-label")
    if opp_type and not any(a in opp_type.lower() for a in {"solicitation","presolicitation","sources sought","special notice","grant","cooperative agreement"}):
        print(f"    [filtered] opp_type='{opp_type}' | {opp_id}"); return None

    mena    = matches(body, MENA_COUNTRIES)
    if not mena:    print(f"    [filtered] no MENA | {opp_id}"); return None
    matched = matches(body, KEYWORDS)
    if not matched: print(f"    [filtered] no keywords | mena={mena} | {opp_id}"); return None

    title    = get_css(soup, "h1,[class*='opportunity-title'],[class*='opp-title']")
    donor    = get_css(soup, "[class*='organization'],[class*='agency-name'],[class*='dept']")
    deadline = get_css(soup, "[class*='deadline'],[class*='response-date'],[class*='responseDeadline'],.response-deadline")
    amt_max  = parse_amount(get_css(soup, "[class*='award-amount'],[class*='amount']"))
    external = [a.get("href") for a in soup.select("a[href^='http']") if a.get("href") and "sam.gov" not in a.get("href")]
    opp_data = {"Title": title, "Donor Name": donor, "Geographic Area": ", ".join(mena), "Focus / Sector": infer_sector(matched), "Eligibility": parse_eligibility(body), "Amount Max (USD)": amt_max[1], "Application Deadline": deadline}

    return {"Opportunity ID": opp_id, "Opportunity Type": opp_type, "Title": title, "Donor Name": donor, "Geographic Area": ", ".join(mena), "Focus / Sector": infer_sector(matched), "Application Deadline": deadline, "Amount Min (USD)": amt_max[0], "Amount Max (USD)": amt_max[1], "Eligibility": parse_eligibility(body), "Matched Keywords": " | ".join(matched), "Source Link": opp_url, "Original Link": external[0] if external else "", "Date Posted": get_css(soup, "[class*='posted-date'],[class*='postDate']"), "AI Summary": None, "_opp_data": opp_data}


def run(max_pages=10):
    df, existing_ids = pd.DataFrame(columns=COLUMNS), set()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for i, keyword in enumerate(KEYWORDS, 1):
        print(f"\n{'='*50}\n  KEYWORD [{i:3}/{len(KEYWORDS)}] '{keyword}'\n{'='*50}")
        opp_urls = [url for pg in range(1, max_pages + 1) for url in (get_links(session, keyword, pg, existing_ids) or [None]) if url]
        if not opp_urls: print("  [INFO] No new opportunities found."); continue

        for j, url in enumerate(opp_urls, 1):
            print(f"  [{j:02d}/{len(opp_urls)}] {url}")
            row = scrape_detail(session, url)
            if row is None: print("        → Filtered out."); continue
            print(f"        ✓ '{row['Title'][:55]}'\n          KW: {row['Matched Keywords'][:75]}")
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            existing_ids.add(row["Opportunity ID"])

    print(f"\nGenerating AI summaries for {len(df)} opportunities...")
    for idx, row in df.iterrows():
        if row.get("_opp_data"): df.at[idx, "AI Summary"] = generate_sam_summary(row["_opp_data"])
    df = df.drop(columns=["_opp_data"])

    print(f"\n{'='*50}\n  Done — {len(df)} matching rows\n{'='*50}\n")
    pd.set_option("display.max_columns", None); pd.set_option("display.max_colwidth", 60); pd.set_option("display.width", 220)
    print(df.to_string(index=False))

    SHEET_NAME = "sam"
    if os.path.exists(EXCEL_FILE):
        if SHEET_NAME in pd.ExcelFile(EXCEL_FILE).sheet_names:
            new_rows = df[~df["Opportunity ID"].isin(set(pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)["Opportunity ID"]))]
            if not new_rows.empty:
                with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
                    new_rows.to_excel(writer, sheet_name=SHEET_NAME, startrow=writer.book[SHEET_NAME].max_row, index=False, header=False)
                print(f"Added {len(new_rows)} new grants")
            else: print("No new grants")
        else:
            with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a") as writer: df.to_excel(writer, sheet_name=SHEET_NAME, index=False)
            print(f"Created new sheet '{SHEET_NAME}'")
    else:
        df.to_excel(EXCEL_FILE, sheet_name=SHEET_NAME, index=False); print("Created new Excel file")

    return df


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SAM.gov MENA grant scraper (no Playwright)")
    p.add_argument("--pages", type=int, default=10, help="Pages per keyword (default: 10)")
    args = p.parse_args()
    print(f"Pages: {args.pages}")
    run(args.pages)
