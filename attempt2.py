import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

BASE_URL = "https://darpe.me"
LISTING_URL = "https://darpe.me/tenders-and-grants/"  # replace with actual listing URL

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

#PART 1: SCRAPES FROM LIST ON TABLE PAGE AND CONVERTS TO CSV FILE

def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def extract_client_name(td):
    text = clean_text(td.get_text(" ", strip=True))
    match = re.search(r"Client Name\s*:\s*(.+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def extract_listing_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    # print(soup)
    rows = soup.select("tr.whiteBackground, tr.graybackground, tr.grayBackground")
    results = []

    for row in rows:
        tds = row.find_all("td")
        if not tds:
            continue

        # 1) title + detail page link
        title_link = row.select_one("a[href*='darpe-entries']")
        title = clean_text(title_link.get_text()) if title_link else ""
        detail_page_url = urljoin(BASE_URL, title_link["href"]) if title_link and title_link.has_attr("href") else ""

        # 2) donor name from "Client Name : ..."
        donor_name = ""
        if title_link:
            parent_td = title_link.find_parent("td")
            if parent_td:
                donor_name = extract_client_name(parent_td)

        # 3) deadline
        deadline = clean_text(tds[2].get_text(" ", strip=True)) if len(tds) > 2 else ""

        # 4) sector/services
        focus_sector = clean_text(tds[3].get_text(" ", strip=True)) if len(tds) > 3 else ""

        # 5) geography
        geographic_area = clean_text(tds[4].get_text(" ", strip=True)) if len(tds) > 4 else ""

        # Access inner link
        try:
            res = requests.get(detail_page_url, headers=HEADERS)
            res.raise_for_status()

            info_soup = BeautifulSoup(res.text, "html.parser")

            page_title = info_soup.title.get_text(strip=True) if info_soup.title else "No Title"
            # print(f"Landed on page: {page_title}")

            info_table = info_soup.select("div.gray-bg")
            # if not info_table:
            #     print(f"--> Warning: 'div.gray-bg' not found on {detail_page_url}")
            # else:
            #     print(f"--> Success! Found target div.")
            #     print(info_table)
            
            # lis = info_table[0].find_all("li")
            # if not lis:
            #     continue
            # print(lis)
        except Exception as e:
            print(f"Error crawling {detail_page_url}: {e}")
        
        # 6) pdfs
        # follow up once we get access

        # 7) og link
        # follow up once we get access

        results.append({
            "title": title,
            "detail_page_url": detail_page_url,
            "donor_name": donor_name,
            "deadline": deadline,
            "focus_sector": focus_sector,
            "geographic_area": geographic_area,
        })

    return results

def fetch_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

html = fetch_html(LISTING_URL)
listing_items = extract_listing_rows(html)

df = pd.DataFrame(listing_items)
print(df.head())
wb = Workbook()
ws = wb.active
ws.title = "Tenders & Grants"

# Header row
headers = ["Title", "Detail Page URL", "Donor Name", "Deadline", "Focus Sector", "Geographic Area"]
ws.append(headers)

# Style header row
for cell in ws[1]:
    cell.font = Font(bold=True, color="FFFFFF", name="Arial")
    cell.fill = PatternFill("solid", start_color="2E4057")
    cell.alignment = Alignment(horizontal="center")

# Data rows
for _, row in df.iterrows():
    ws.append([
        row["title"],
        row["detail_page_url"],
        row["donor_name"],
        row["deadline"],
        row["focus_sector"],
        row["geographic_area"],
    ])

# Auto-fit column widths
col_widths = [60, 50, 30, 20, 30, 25]
for i, width in enumerate(col_widths, start=1):
    ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width

# Freeze header row
ws.freeze_panes = "A2"

wb.save("tenders_grants.xlsx")
print("Saved to tenders_grants.xlsx")

def extract_detail_page(detail_url):
    html = fetch_html(detail_url)
    soup = BeautifulSoup(html, "html.parser")

    # collect all links
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(detail_url, a["href"])
        text = clean_text(a.get_text(" ", strip=True))
        links.append({"text": text, "href": href})

    # PDFs
    pdf_links = [link["href"] for link in links if ".pdf" in link["href"].lower()]

    # source/original link heuristics
    source_link = ""
    original_link = ""

    for link in links:
        text_lower = link["text"].lower()
        href_lower = link["href"].lower()

        if not source_link and ("source" in text_lower or "official" in text_lower):
            source_link = link["href"]

        if not original_link and ("original" in text_lower or "apply" in text_lower or "full notice" in text_lower):
            original_link = link["href"]

    # if there are no labeled links, try picking first non-darpe external link
    external_links = [
        link["href"] for link in links
        if "darpe.me" not in link["href"]
    ]

    if not source_link and external_links:
        source_link = external_links[0]

    if not original_link and len(external_links) > 1:
        original_link = external_links[1]

    # description text
    content_candidates = soup.select("article, .entry-content, .post-content, .content, .elementor-widget-container")
    full_description = ""
    if content_candidates:
        full_description = clean_text(" ".join(c.get_text(" ", strip=True) for c in content_candidates))
    else:
        full_description = clean_text(soup.get_text(" ", strip=True))

    return {
        "pdf_links": pdf_links,
        "source_link": source_link,
        "original_link": original_link,
        "full_description": full_description,
    }
    
