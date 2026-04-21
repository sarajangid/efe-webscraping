"""
Grabs one random grant from SAM.gov, EU Comm, and Simpler Grants,
generates an AI summary for each, and prints to terminal.
"""

import asyncio
import re
import urllib.parse
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from summarizer import generate_sam_summary, generate_simpler_summary

SAM_URL = (
    "https://sam.gov/search/?index=_all&sort=-modifiedDate"
    "&sfm%5Bstatus%5D%5Bis_active%5D=true"
    "&sfm%5BsimpleSearch%5D%5BkeywordRadio%5D=ALL"
    "&page=1&pageSize=25"
    f"&sfm%5BsimpleSearch%5D%5BkeywordTags%5D%5B0%5D%5Bvalue%5D={urllib.parse.quote('education')}"
)
EU_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
    "opportunities/calls-for-proposals"
)
SIMPLER_URL = "https://simpler.grants.gov/search?query=education"


def _divider(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


async def fetch_sam(context):
    _divider("SAM.gov")
    page = await context.new_page()
    try:
        print("Navigating to SAM.gov listing...")
        await page.goto(SAM_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("a[href*='/opp/']", timeout=15000)

        hrefs = await page.eval_on_selector_all(
            "a[href*='/opp/']",
            "els => [...new Set(els.map(e => e.href))]",
        )
        if not hrefs:
            print("No SAM.gov opportunities found.")
            return

        opp_url = hrefs[0]
        print(f"Opening: {opp_url[:80]}...")
        await page.goto(opp_url, wait_until="domcontentloaded", timeout=30000)
        body = await page.inner_text("body", timeout=10000)

        title = await page.title()
        opp_data = {
            "Title": title,
            "Donor Name": "",
            "Geographic Area": "",
            "Focus / Sector": "",
            "Eligibility": "",
            "Amount Max (USD)": "",
            "Application Deadline": "",
            "body": body,
        }
        print("Generating AI summary...")
        summary = generate_sam_summary(opp_data)
        print(f"\nTitle:   {title}")
        print(f"URL:     {opp_url}")
        print(f"Summary: {summary}")
    except PwTimeout as e:
        print(f"Timeout: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await page.close()


async def fetch_eu_comm(context):
    _divider("EU Commission")
    page = await context.new_page()
    try:
        print("Navigating to EU Comm listing...")
        await page.goto(EU_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector('div:has-text("Deadline")', timeout=15000, state="attached")

        cards = page.locator("div").filter(has_text="Deadline")
        count = await cards.count()
        if not count:
            print("No EU Comm cards found.")
            return

        card = cards.nth(0)
        text = await card.inner_text(timeout=5000)
        link_el = card.locator("a").first
        if not await link_el.count():
            print("No link on first card.")
            return

        link = await link_el.get_attribute("href", timeout=5000)
        from urllib.parse import urljoin
        full_link = urljoin(EU_URL, link)

        print(f"Opening: {full_link[:80]}...")
        detail = await context.new_page()
        await detail.goto(full_link, wait_until="domcontentloaded", timeout=15000)
        body = await detail.inner_text("body", timeout=8000)
        await detail.close()

        title = text.split("\n")[0].strip()
        opp_data = {
            "Title": title,
            "Donor Name": "European Commission",
            "Geographic Area": "",
            "Focus / Sector": "",
            "Eligibility": "",
            "Amount Max (USD)": "",
            "Application Deadline": "",
            "body": body,
        }
        print("Generating AI summary...")
        summary = generate_sam_summary(opp_data)
        print(f"\nTitle:   {title}")
        print(f"URL:     {full_link}")
        print(f"Summary: {summary}")
    except PwTimeout as e:
        print(f"Timeout: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await page.close()


async def fetch_simpler(context):
    _divider("Simpler Grants (grants.gov)")
    page = await context.new_page()
    try:
        print("Navigating to Simpler Grants listing...")
        await page.goto(SIMPLER_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("tr.border-base", timeout=15000)

        hrefs = await page.eval_on_selector_all(
            "tr.border-base a[href]",
            "els => [...new Set(els.map(e => e.href))]",
        )
        if not hrefs:
            print("No Simpler Grants results found.")
            return

        full_link = hrefs[0] if hrefs[0].startswith("http") else "https://simpler.grants.gov" + hrefs[0]
        print(f"Opening: {full_link[:80]}...")

        detail = await context.new_page()
        await detail.goto(full_link, wait_until="domcontentloaded", timeout=30000)

        title = (await detail.query_selector("h2") or await detail.query_selector("h1"))
        title_text = await title.inner_text() if title else await detail.title()

        body_el = await detail.query_selector("body")
        body = await body_el.inner_text() if body_el else ""
        await detail.close()

        print("Generating AI summary...")
        summary = generate_simpler_summary(body[:3000])
        print(f"\nTitle:   {title_text}")
        print(f"URL:     {full_link}")
        print(f"Summary: {summary}")
    except PwTimeout as e:
        print(f"Timeout: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await page.close()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        await fetch_sam(context)
        await fetch_eu_comm(context)
        await fetch_simpler(context)

        await browser.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
