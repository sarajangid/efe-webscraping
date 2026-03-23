from summarizer import generate_sam_summary
import argparse, re, time
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from reqs import *

BASE_URL = "https://www.developmentaid.org/tenders/search?sort=relevance.desc&searchedText=grants"

def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()

def matches(text, terms):
    return [t for t in terms if t.lower() in text.lower()]

def parse_amount(text):
    nums = [a.replace(",", "") for a in re.findall(r"[\$€£]?\s*([\d,]+(?:\.\d+)?)", text or "")]
    return ("", "") if not nums else (nums[0], nums[0]) if len(nums) == 1 else (nums[0], nums[-1])

def get(page, sel):
    el = page.query_selector(sel)
    return norm(el.inner_text()) if el else ""

def get_links(page):
    """Return deduplicated list of {href, surface} dicts from a listing page."""
    cards = (
        page.query_selector_all(
            "div.tender-item, article.tender-card, .search-results .item, "
            "[class*='TenderCard'], li.result-item, .result-list > div"
        ) or page.query_selector_all("a[href*='/tenders/']")
    )
    print(f"  Found {len(cards)} cards")
    seen, out = set(), []
    for card in cards:
        try:
            el = card.query_selector("a[href*='/tenders/']") or card
            href = el.get_attribute("href") or ""
            if "/tenders/" not in href or href in seen: continue
            if not href.startswith("http"): href = "https://www.developmentaid.org" + href
            seen.add(href)
            out.append({"href": href, "surface": norm(card.inner_text())})
        except Exception:
            continue
    return out

def scrape_detail(page, href, source_url):
    """Scrape a detail page; return row dict or None if filtered out."""
    try:
        page.goto(href, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3000)
    except PwTimeout:
        print(f"    [WARN] Timeout: {href}")
        return None

    try:
        body = norm(page.inner_text("body"))
    except Exception:
        body = ""

    opp_type = get(page, "[class*='type'],[class*='Type'],.badge,.tag,[class*='category']")
    if opp_type and "grant" not in opp_type.lower():
        sidebar = get(page, "aside,.tender-sidebar,.summary,[class*='summary'],[class*='details'],.metadata")
        if "grant" not in sidebar.lower() and "grant" not in body[:2000].lower(): return None

    geo = get(page, "[class*='location'],[class*='Location'],[class*='country'],[class*='Country'],[class*='region']")
    mena_hits = matches(geo + " " + body[:3000], MENA_COUNTRIES)
    if not mena_hits: return None
    kw_hits = matches(body, KEYWORDS)
    if not kw_hits: return None

    m = re.search(r"/tenders/(\d+)", href)
    opp_id = m.group(1) if m else re.sub(r"\W", "", href)[-12:]
    amt_min, amt_max = parse_amount(
        get(page, "[class*='amount'],[class*='Amount'],[class*='budget'],[class*='Budget'],[class*='funding']")
    )

    # Build opportunity dict for AI summary
    opportunity = {
        "Title": get(page, "h1,[class*='title'] h1,[class*='Title']") or "N/A",
        "Donor Name": get(page, "[class*='donor'],[class*='Donor'],[class*='funder'],[class*='client'],[class*='organisation']"),
        "Geographic Area": geo or ", ".join(mena_hits),
        "Focus / Sector": get(page, "[class*='sector'],[class*='Sector'],[class*='focus'],[class*='theme']"),
        "Eligibility": get(page, "[class*='eligib'],[class*='Eligib'],[class*='applicant'],[class*='eligible']"),
        "Amount Max (USD)": amt_max,
        "Application Deadline": get(page, "[class*='deadline'],[class*='Deadline'],[class*='closing'],time[datetime]"),
    }
    ai_summary = generate_sam_summary(opportunity)

    return {
        "Opportunity ID":       opp_id,
        "Opportunity Type":     opp_type or "Grant",
        "Title":                get(page, "h1,[class*='title'] h1,[class*='Title']") or "N/A",
        "Donor Name":           get(page, "[class*='donor'],[class*='Donor'],[class*='funder'],[class*='client'],[class*='organisation']"),
        "Geographic Area":      geo or ", ".join(mena_hits),
        "Focus / Sector":       get(page, "[class*='sector'],[class*='Sector'],[class*='focus'],[class*='theme']"),
        "Application Deadline": get(page, "[class*='deadline'],[class*='Deadline'],[class*='closing'],time[datetime]"),
        "Amount Min (USD)":     amt_min,
        "Amount Max (USD)":     amt_max,
        "Eligibility":          get(page, "[class*='eligib'],[class*='Eligib'],[class*='applicant'],[class*='eligible']"),
        "Matched Keywords":     "; ".join(kw_hits),
        "Source Link":          source_url,
        "Original Link":        href,
        "Date Posted":          get(page, "[class*='posted'],[class*='Published'],[class*='published'],time"),
        "AI Summary":           ai_summary
    }

def run(max_pages=10, headless=False):
    df = pd.DataFrame(columns=COLUMNS)
    seen_ids, seen_links = set(), set()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        ).new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        lp, dp = ctx.new_page(), ctx.new_page()

        for pn in range(1, max_pages + 1):
            print(f"\n{'='*50}\n  PAGE {pn}/{max_pages}\n{'='*50}")
            source = BASE_URL + f"&page={pn}"
            try:
                lp.goto(source, wait_until="domcontentloaded", timeout=30_000)
                lp.wait_for_timeout(4000)
                lp.wait_for_selector(
                    "div.tender-item,article.tender-card,.search-results .item,"
                    "[class*='tender'],[class*='opportunity'],.card",
                    timeout=15_000,
                )
            except PwTimeout:
                print("  [WARN] Page load timeout, stopping.")
                break

            entries = get_links(lp)
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

                row = scrape_detail(dp, href, source)
                if row is None:
                    print("        → Filtered out.")
                    continue

                print(f"        ✓ '{row['Title'][:55]}'\n          KW: {row['Matched Keywords'][:75]}")
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
                seen_ids.add(str(row["Opportunity ID"]))
                seen_links.add(href)
                time.sleep(0.5)

        ctx.browser.close()

    print(f"\n{'='*50}\n  Done — {len(df)} matching rows\n{'='*50}\n")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", 60)
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))
    return df

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="DevelopmentAid MENA grant scraper")
    p.add_argument("--pages", type=int, default=10, help="Pages to scrape (default: 10)")
    p.add_argument("--headless", action="store_true", help="Run headless")
    args = p.parse_args()
    print(f"Pages: {args.pages} | Headless: {args.headless}")
    run(args.pages, args.headless)