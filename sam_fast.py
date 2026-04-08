import argparse, re, urllib.parse
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
import os
from dotenv import load_dotenv
from summarizer import generate_sam_summary
from reqs import MENA_COUNTRIES, KEYWORDS, COLUMNS
from dev_aid import norm, get, matches, parse_amount

load_dotenv()
EXCEL_FILE = os.environ["EXCEL_FILE"]

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

HEADER_COLOR = "1F4E79"
HEADER_FILL = PatternFill(start_color=HEADER_COLOR, end_color=HEADER_COLOR, fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
BODY_ALIGNMENT = Alignment(vertical="top", wrap_text=True)

DEFAULT_WIDTHS = {
    "Opportunity ID": 18,
    "Opportunity Type": 22,
    "Title": 40,
    "Donor Name": 28,
    "Geographic Area": 24,
    "Focus / Sector": 28,
    "Application Deadline": 20,
    "Amount Min (USD)": 18,
    "Amount Max (USD)": 18,
    "Eligibility": 42,
    "Eligibility Requirements": 45,
    "Matched Keywords": 32,
    "Source Link": 45,
    "Original Link": 45,
    "Date Posted": 18,
    "Date Scraped": 16,
    "Grant Name": 38,
    "Agency": 28,
    "Due Date": 18,
    "Award Minimum": 18,
    "Award Maximum": 18,
    "Description": 65,
    "Documents": 45,
    "Application Link": 45,
    "AI Summary": 65,
    "Post Link": 50,
    "Funding Amount (USD)": 22,
    "Grant Link": 45,
    "Deadline": 18,
}

def _auto_width(header: str) -> float:
    header = (header or "").strip()
    if not header:
        return 18
    return min(max(len(header) + 4, 18), 45)

def apply_impact_formatting(path: str, sheet_name: str, custom_widths=None):
    wb = openpyxl.load_workbook(path)

    if sheet_name not in wb.sheetnames:
        wb.save(path)
        return

    ws = wb[sheet_name]
    widths = {**DEFAULT_WIDTHS, **(custom_widths or {})}

    if ws.max_row >= 1:
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=col_idx)
            header = "" if cell.value is None else str(cell.value)

            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGNMENT

            ws.column_dimensions[get_column_letter(col_idx)].width = widths.get(
                header, _auto_width(header)
            )

        ws.row_dimensions[1].height = 30

    for row_idx in range(2, ws.max_row + 1):
        ws.row_dimensions[row_idx].height = 80
        for col_idx in range(1, ws.max_column + 1):
            ws.cell(row=row_idx, column=col_idx).alignment = BODY_ALIGNMENT

    ws.freeze_panes = "A2"
    wb.save(path)

BASE_URL = "https://sam.gov/search/?index=_all&sort=-modifiedDate&sfm%5Bstatus%5D%5Bis_active%5D=true&sfm%5Bstatus%5D%5Bis_inactive%5D=true&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL"

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

def get_links(page, keyword, pg, existing_ids):
    try:
        page.goto(f"{BASE_URL}&page={pg}&pageSize=25&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D={urllib.parse.quote(keyword)}", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("a[href*='/opp/']", timeout=10_000)
    except PwTimeout: return []
    hrefs = list({urllib.parse.urljoin("https://sam.gov", a.get_attribute("href")) for a in
                  page.query_selector_all("a[href*='/opp/']") if a.get_attribute("href")})
    #hrefs = list({a.get_attribute("href") for a in page.query_selector_all("a[href*='/opp/']") if a.get_attribute("href")})
    print(f"    [debug] page {pg} | hrefs found: {len(hrefs)}")
    return [h for h in hrefs if (m := re.search(r"/opp/([^/]+)/", h)) and m.group(1) not in existing_ids]

def scrape_detail(page, opp_url):
    if not (m := re.search(r"/opp/([^/]+)/", opp_url)): return None
    opp_id = m.group(1)
    try:
        page.goto(opp_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("[class*='opportunity-title'],[class*='opp-title'],h1", timeout=15_000)
        page.wait_for_timeout(1500)
        body = norm(page.inner_text("body"))

        opp_type = get(page, "[class*='notice-type'],[class*='opportunity-type'],[class*='noticeType'],.type-label")
        if opp_type and not any(a in opp_type.lower() for a in {"solicitation","presolicitation","sources sought","special notice","grant","cooperative agreement"}):
            print(f"    [filtered] opp_type='{opp_type}' | {opp_id}"); return None

        mena    = matches(body, MENA_COUNTRIES)
        if not mena:    print(f"    [filtered] no MENA | {opp_id}"); return None
        matched = matches(body, KEYWORDS)
        if not matched: print(f"    [filtered] no keywords | mena={mena} | {opp_id}"); return None

        title    = get(page, "h1,[class*='opportunity-title'],[class*='opp-title']")
        donor    = get(page, "[class*='organization'],[class*='agency-name'],[class*='dept']")
        deadline = get(page, "[class*='deadline'],[class*='response-date'],[class*='responseDeadline'],.response-deadline")
        amt_max  = parse_amount(get(page, "[class*='award-amount'],[class*='amount']"))
        external = [a.get_attribute("href") for a in page.query_selector_all("a[href^='http']") if a.get_attribute("href") and "sam.gov" not in a.get_attribute("href")]
        opp_data = {"Title": title, "Donor Name": donor, "Geographic Area": ", ".join(mena), "Focus / Sector": infer_sector(matched), "Eligibility": parse_eligibility(body), "Amount Max (USD)": amt_max[1], "Application Deadline": deadline}

        return {"Opportunity ID": opp_id, "Opportunity Type": opp_type, "Title": title, "Donor Name": donor, "Geographic Area": ", ".join(mena), "Focus / Sector": infer_sector(matched), "Application Deadline": deadline, "Amount Min (USD)": amt_max[0], "Amount Max (USD)": amt_max[1], "Eligibility": parse_eligibility(body), "Matched Keywords": " | ".join(matched), "Source Link": opp_url, "Original Link": external[0] if external else "", "Date Posted": get(page, "[class*='posted-date'],[class*='postDate']"), "AI Summary": None, "_opp_data": opp_data}
    except PwTimeout:
        print(f"    [WARN] Timeout: {opp_url}"); return None
    except Exception as exc:
        print(f"    Error on {opp_url}: {exc}"); return None


def run(max_pages=10, headless=True):
    df, existing_ids = pd.DataFrame(columns=COLUMNS), set()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"]).new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        lp, dp = ctx.new_page(), ctx.new_page()

        for i, keyword in enumerate(KEYWORDS, 1):
            print(f"\n{'='*50}\n  KEYWORD [{i:3}/{len(KEYWORDS)}] '{keyword}'\n{'='*50}")
            opp_urls = [url for pg in range(1, max_pages + 1) for url in (get_links(lp, keyword, pg, existing_ids) or [None]) if url]
            if not opp_urls: print("  [INFO] No new opportunities found."); continue

            for j, url in enumerate(opp_urls, 1):
                print(f"  [{j:02d}/{len(opp_urls)}] {url}")
                row = scrape_detail(dp, url)
                if row is None: print("        → Filtered out."); continue
                print(f"        ✓ '{row['Title'][:55]}'\n          KW: {row['Matched Keywords'][:75]}")
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
                existing_ids.add(row["Opportunity ID"])

        ctx.browser.close()

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
    apply_impact_formatting(EXCEL_FILE, SHEET_NAME)
    return df


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SAM.gov MENA grant scraper")
    p.add_argument("--pages", type=int, default=10, help="Pages per keyword (default: 10)")
    p.add_argument("--headless", action="store_true", help="Run headless")
    args = p.parse_args()
    print(f"Pages: {args.pages} | Headless: {args.headless}")
    run(args.pages, args.headless)