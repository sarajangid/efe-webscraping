from summarizer import generate_sam_summary
import argparse, re, time
import pandas as pd
import requests
from bs4 import BeautifulSoup
from reqs import *
import os
from dotenv import load_dotenv

load_dotenv()
EXCEL_FILE = os.environ["EXCEL_FILE"]

BASE_URL = "https://www.developmentaid.org/tenders/search?sort=relevance.desc&searchedText=grants"
SITE_BASE = "https://www.developmentaid.org"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()

def matches(text, terms):
    return [t for t in terms if t.lower() in text.lower()]

def parse_amount(text):
    nums = [a.replace(",", "") for a in re.findall(r"[\$€£]?\s*([\d,]+(?:\.\d+)?)", text or "")]
    return ("", "") if not nums else (nums[0], nums[0]) if len(nums) == 1 else (nums[0], nums[-1])

def get(soup, sel):
    el = soup.select_one(sel)
    return norm(el.get_text(separator=" ", strip=True)) if el else ""

def get_links(soup):
    """Return deduplicated list of {href, surface} dicts from a listing page."""
    cards = (
        soup.select(
            "div.tender-item, article.tender-card, .search-results .item, "
            "[class*='TenderCard'], li.result-item, .result-list > div"
        ) or soup.select("a[href*='/tenders/']")
    )
    print(f"  Found {len(cards)} cards")
    seen, out = set(), []
    for card in cards:
        try:
            el = card.select_one("a[href*='/tenders/']") or card
            href = el.get("href") or ""
            if "/tenders/" not in href or href in seen: continue
            if not href.startswith("http"): href = SITE_BASE + href
            seen.add(href)
            out.append({"href": href, "surface": norm(card.get_text(separator=" ", strip=True))})
        except Exception:
            continue
    return out

def scrape_detail(session, href, source_url):
    """Scrape a detail page; return row dict or None if filtered out."""
    try:
        resp = session.get(href, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        print(f"    [WARN] Request failed: {href}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    body = norm(soup.get_text(separator=" "))

    opp_type = get(soup, "[class*='type'],[class*='Type'],.badge,.tag,[class*='category']")
    if opp_type and "grant" not in opp_type.lower():
        sidebar = get(soup, "aside,.tender-sidebar,.summary,[class*='summary'],[class*='details'],.metadata")
        if "grant" not in sidebar.lower() and "grant" not in body[:2000].lower(): return None

    geo = get(soup, "[class*='location'],[class*='Location'],[class*='country'],[class*='Country'],[class*='region']")
    mena_hits = matches(geo + " " + body[:3000], MENA_COUNTRIES)
    if not mena_hits: return None
    kw_hits = matches(body, KEYWORDS)
    if not kw_hits: return None

    m = re.search(r"/tenders/(\d+)", href)
    opp_id = m.group(1) if m else re.sub(r"\W", "", href)[-12:]
    amt_min, amt_max = parse_amount(
        get(soup, "[class*='amount'],[class*='Amount'],[class*='budget'],[class*='Budget'],[class*='funding']")
    )

    title = get(soup, "h1,[class*='title'] h1,[class*='Title']") or "N/A"
    donor = get(soup, "[class*='donor'],[class*='Donor'],[class*='funder'],[class*='client'],[class*='organisation']")
    sector = get(soup, "[class*='sector'],[class*='Sector'],[class*='focus'],[class*='theme']")
    eligibility = get(soup, "[class*='eligib'],[class*='Eligib'],[class*='applicant'],[class*='eligible']")
    deadline = get(soup, "[class*='deadline'],[class*='Deadline'],[class*='closing'],time[datetime]")

    return {
        "Opportunity ID":       opp_id,
        "Opportunity Type":     opp_type or "Grant",
        "Title":                title,
        "Donor Name":           donor,
        "Geographic Area":      geo or ", ".join(mena_hits),
        "Focus / Sector":       sector,
        "Application Deadline": deadline,
        "Amount Min (USD)":     amt_min,
        "Amount Max (USD)":     amt_max,
        "Eligibility":          eligibility,
        "Matched Keywords":     "; ".join(kw_hits),
        "Source Link":          source_url,
        "Original Link":        href,
        "Date Posted":          get(soup, "[class*='posted'],[class*='Published'],[class*='published'],time"),
        "AI Summary":           None,
        "_opp_data":            {
            "Title": title,
            "Donor Name": donor,
            "Geographic Area": geo or ", ".join(mena_hits),
            "Focus / Sector": sector,
            "Eligibility": eligibility,
            "Amount Max (USD)": amt_max,
            "Application Deadline": deadline,
        },
    }

def run(max_pages=10):
    df = pd.DataFrame(columns=COLUMNS)
    seen_ids, seen_links = set(), set()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for pn in range(1, max_pages + 1):
        print(f"\n{'='*50}\n  PAGE {pn}/{max_pages}\n{'='*50}")
        source = BASE_URL + f"&page={pn}"
        try:
            resp = session.get(source, timeout=30)
            resp.raise_for_status()
        except requests.RequestException:
            print("  [WARN] Page load failed, stopping.")
            break

        listing_soup = BeautifulSoup(resp.text, "html.parser")
        entries = get_links(listing_soup)
        if not entries:
            print("  [INFO] No entries found, end of results.")
            break

        for i, e in enumerate(entries, 1):
            href = e["href"]
            m = re.search(r"/tenders/(\d+)", href)
            oid = m.group(1) if m else ""
            print(f"  [{i:02d}/{len(entries)}] {href}")
            if href in seen_links or (oid and oid in seen_ids):
                print("        → Duplicate, skipping.")
                continue

            row = scrape_detail(session, href, source)
            if row is None:
                print("        → Filtered out.")
                continue

            print(f"        ✓ '{row['Title'][:55]}'\n          KW: {row['Matched Keywords'][:75]}")
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            seen_ids.add(str(row["Opportunity ID"]))
            seen_links.add(href)
            time.sleep(0.5)

    # Generate AI summaries in batch for all filtered results
    print(f"\nGenerating AI summaries for {len(df)} opportunities...")
    for idx, row in df.iterrows():
        if row.get("_opp_data"):
            df.at[idx, "AI Summary"] = generate_sam_summary(row["_opp_data"])
    # Drop the temporary _opp_data column
    df = df.drop(columns=["_opp_data"])

    print(f"\n{'='*50}\n  Done — {len(df)} matching rows\n{'='*50}\n")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", 60)
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))


    SHEET_NAME = "eu_comm"

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
            with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a") as writer:
                df.to_excel(writer, sheet_name=SHEET_NAME, index=False)
            print(f"Created new sheet '{SHEET_NAME}'")

    else:
        df.to_excel(EXCEL_FILE, sheet_name=SHEET_NAME, index=False)
        print("Created new Excel file")

    return df

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="DevelopmentAid MENA grant scraper (no Playwright)")
    p.add_argument("--pages", type=int, default=10, help="Pages to scrape (default: 10)")
    args = p.parse_args()
    print(f"Pages: {args.pages}")
    run(args.pages)
