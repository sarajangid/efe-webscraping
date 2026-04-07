from summarizer import generate_sam_summary
import asyncio
import pandas as pd
import re
import time
from urllib.parse import urljoin
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import os
from dotenv import load_dotenv

BASE_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals"

load_dotenv()
EXCEL_FILE = os.environ["EXCEL_FILE"]

MENA_COUNTRIES = [
    "Morocco","Algeria","Tunisia","Egypt","Jordan","Palestine","Palestinian",
    "West Bank","Gaza","Yemen","UAE","United Arab Emirates","Saudi Arabia",
    "Lebanon","Bahrain","Syria","MENA","Middle East","North Africa",
    "Arab World","GCC","Maghreb","Levant",
]

KEYWORDS = [
    "youth employment","workforce development","employability","job placement",
    "job creation","livelihoods","economic empowerment","economic inclusion",
    "apprenticeship","internship","mentorship","job readiness","job search",
    "labor market activation","economic participation","labor market entry",
    "NEET","work readiness","job seekers","early-career","reducing inequalities",
    "skills development","vocational training","technical training","soft skills",
    "digital skills","green jobs","green skills","TVET","upskilling","resciling",
    "entrepreneurship","SME development","financial inclusion","gig economy",
]

# ✅ UPDATED: Added "AI Summary" and "Full_Description" (temp storage)
COLUMNS = [
    "Opportunity ID","Title","Application Deadline","Matched Keywords",
    "Geographic Area","Original Link", "Full_Description", "AI Summary"
]

def contains_mena(text):
    if not text:
        return []
    text_lower = text.lower()
    return [c for c in MENA_COUNTRIES if c.lower() in text_lower]

def find_keywords(text):
    if not text:
        return []
    text_lower = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in text_lower]

async def scrape():
    rows = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()

        print("🌐 Opening page...")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_load_state("networkidle", timeout=30000)

        for page_num in range(10):
            print(f"\n🔎 Scraping page {page_num + 1}\n")

            for i in range(50):  # ✅ FIX: Dynamic card iteration instead of pre-fetching
                try:
                    # ✅ FIX: Re-fetch cards list on every iteration to avoid stale references
                    await page.wait_for_selector('div:has-text("Deadline")', timeout=10000, state="attached")
                    cards = page.locator("div").filter(has_text="Deadline")
                    count = await cards.count()
                    
                    if i >= count:
                        print(f"ℹ️ Reached end of cards ({count}) on page {page_num + 1}")
                        break
                        
                    card = cards.nth(i)
                    
                    if not await card.is_visible(timeout=5000):
                        print(f"️ Card {i+1} no longer visible, skipping")
                        continue
                        
                    text = await card.inner_text(timeout=10000)
                    print(f"\n---\n📌 Card {i+1}")

                    link_el = card.locator("a").first
                    if not await link_el.count():
                        print("❌ REJECTED: No link element found")
                        continue
                        
                    link = await link_el.get_attribute("href", timeout=10000)
                    if not link:
                        print("❌ REJECTED: No href attribute")
                        continue

                    full_link = urljoin(BASE_URL, link)
                    print(f"🔗 Navigating to: {full_link[:80]}...")

                    try:
                        await page.goto(full_link, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except PlaywrightTimeout:
                        print(f"⚠️ Navigation timeout for {full_link}, trying to continue...")
                    except Exception as e:
                        print(f"❌ Navigation error: {e}")
                        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
                        continue

                    # ✅ CAPTURE FULL TEXT FOR SUMMARIZER LATER
                    content = await page.inner_text("body", timeout=10000)

                    mena_matches = contains_mena(content)
                    if not mena_matches:
                        print("❌ REJECTED: No MENA match")
                        await page.go_back(wait_until="domcontentloaded", timeout=10000)
                        await page.wait_for_load_state("networkidle", timeout=5000)
                        continue
                    else:
                        print(f"✅ MENA: {mena_matches}")

                    keyword_matches = find_keywords(content)
                    if not keyword_matches:
                        print("❌ REJECTED: No keyword match")
                        await page.go_back(wait_until="domcontentloaded", timeout=10000)
                        await page.wait_for_load_state("networkidle", timeout=5000)
                        continue
                    else:
                        print(f"✅ Keywords: {keyword_matches}")

                    print(" ACCEPTED")

                    # ✅ FIX: re module now available for regex
                    deadline = ""
                    deadline_match = re.search(r'Deadline[:\s]+([^\n]+)', text, re.I)
                    if deadline_match:
                        deadline = deadline_match.group(1).strip()

                    # ✅ ADDED: Store full description for later summarization
                    rows.append({
                        "Opportunity ID": "",
                        "Title": text.split("\n")[0].strip(),
                        "Application Deadline": deadline,
                        "Matched Keywords": ", ".join(keyword_matches),
                        "Geographic Area": ", ".join(mena_matches),
                        "Original Link": full_link,
                        "Full_Description": content, # Saved here for AI
                        "AI Summary": "" # Placeholder
                    })

                    await page.go_back(wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_load_state("networkidle", timeout=5000)
                    
                except Exception as e:
                    print(f"❌ Error processing card: {e}")
                    try:
                        if page.url != BASE_URL:
                            await page.go_back(timeout=10000)
                            await page.wait_for_load_state("networkidle", timeout=5000)
                    except:
                        await page.goto(BASE_URL, timeout=30000)
                    continue

            # Pagination
            print("🔄 Checking for next page...")
            next_button = page.locator("button:has-text('Next'):not(:disabled)")
            
            if await next_button.count() > 0 and await next_button.is_visible(timeout=5000):
                print("➡️ Moving to next page...")
                try:
                    await next_button.click(timeout=10000)
                    await page.wait_for_load_state("networkidle", timeout=30000)
                except Exception as e:
                    print(f"⚠️ Could not click next: {e}")
                    break
            else:
                print("⛔ No more pages or next button not found")
                break

        await browser.close()
    
    if rows:
        print(f"\n🤖 Starting AI Summarization for {len(rows)} opportunities...")
        
        for idx, row in enumerate(rows):
            print(f"   Processing {idx+1}/{len(rows)}: {row['Title'][:40]}...")
            
            # Prepare data structure expected by generate_sam_summary
            # We map your EU columns to the keys the function expects
            opp_data = {
                "Title": row.get("Title", ""),
                "Donor Name": "European Commission",
                "Geographic Area": row.get("Geographic Area", ""),
                "Focus / Sector": "", 
                "Eligibility": "",
                "Amount Max (USD)": "",
                "Application Deadline": row.get("Application Deadline", ""),
                "body": row.get("Full_Description", "") # Pass the full scraped text
            }

            try:
                summary = generate_sam_summary(opp_data)
                row["AI Summary"] = summary
            except Exception as e:
                print(f"      ❌ Error generating summary: {e}")
                row["AI Summary"] = "Error generating summary."
            
            #  RATE LIMIT PROTECTION: Pause between calls
            time.sleep(1.5) 

        print("✅ All summaries generated.\n")

    SHEET_NAME = "eu_comm"
    if rows:
        df = pd.DataFrame(rows, columns=COLUMNS)
        print(f"\n✅ Done. Saved {len(rows)} opportunities")
        
        # Drop the temporary Full_Description column before saving to Excel 
        # (Optional: Remove this line if you want the full text in Excel too)
        if "Full_Description" in df.columns:
            df = df.drop(columns=["Full_Description"])
            # Ensure COLUMNS matches for the final save logic if needed, 
            # but passing the DF directly is safer.
            final_columns = [c for c in COLUMNS if c != "Full_Description"]
            df = df[final_columns]

        if os.path.exists(EXCEL_FILE):
            if SHEET_NAME in pd.ExcelFile(EXCEL_FILE).sheet_names:
                existing_df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
                # Simple deduplication based on Title + Link (since ID is empty)
                combined = pd.concat([existing_df, df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["Original Link"], keep="last")
                
                with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="w") as writer:
                    combined.to_excel(writer, sheet_name=SHEET_NAME, index=False)
                print(f"Merged and saved. Total rows: {len(combined)}")
            else:
                with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a") as writer: 
                    df.to_excel(writer, sheet_name=SHEET_NAME, index=False)
                print(f"Created new sheet '{SHEET_NAME}'")
        else:
            df.to_excel(EXCEL_FILE, sheet_name=SHEET_NAME, index=False)
            print("Created new Excel file")

        return df
    else:
        print("\n⚠️ No data collected. Check filters or website structure.")
        return pd.DataFrame(columns=COLUMNS)


if __name__ == "__main__":
    asyncio.run(scrape())