import re
# import urllib3
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from dotenv import load_dotenv
import os
from impact_funding_scraper import generate_darpe_summary

load_dotenv()
# value = os.getenv("MY_KEY")

# # 1. Start a session
# session = requests.Session()

# # # Optional: Add headers so you look like a real browser
# # session.headers.update({
# #     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
# # })

# login_url = "https://example.com/login_endpoint" # The URL the form submits to
# target_url = "https://example.com/protected-detail-page" # The page you actually want to scrape

# user_field_name = os.getenv("USER_FIELD_NAME")
# username = os.getenv("USER_NAME")
# pass_field_name = os.getenv("PASSWORD_FIELD_NAME")
# password = os.getenv("PASSWORD")


# # 2. Create your payload using the exact field names the site expects
# login_data = {
#     user_field_name: username,
#     pass_field_name: password,
#     # Sometimes you need a hidden token here too, like an anti-CSRF token
# }

# # 3. Send the login request
# print("Logging in...")
# login_response = session.post(login_url, data=login_data, verify=False)

# # Optional: Check if login was successful by looking for a specific word in the response
# if "Sign Out" in login_response.text:
#     print("Login successful!")
# else:
#     print("Login might have failed. Check credentials or hidden tokens.")

# # 4. Request the protected page using the SAME session
# detail_response = session.get(target_url)

# # 5. Parse the protected HTML
# soup = BeautifulSoup(detail_response.text, "html.parser")

# # Now you can search for your target elements!
# target_div = soup.select("div.gray_bg") 

BASE_URL = "https://darpe.me"
LISTING_URL = "https://darpe.me/tenders-and-grants/"  # replace with actual listing URL

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

#PART 1: SCRAPES FROM LIST ON TABLE PAGE AND CONVERTS TO CSV FILE

# collapse whitespace and normalize scraped text
def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

#searches for "client name" within title cell. used in extract_listing_rows function
def extract_client_name(td):
    text = clean_text(td.get_text(" ", strip=True))
    match = re.search(r"Client Name\s*:\s*(.+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""

#extracts rows
def extract_listing_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    # print(soup)
    rows = soup.select("tr.whiteBackground, tr.graybackground, tr.grayBackground")
    results = []

    for row in rows:
        tds = row.find_all("td")
        if not tds:
            continue
        
        # 0) type (tender or grant)
        row_text = clean_text(row.get_text(" ", strip=True)).lower()
        if "grant" in row_text:
            listing_type = "Grant"
        elif "tender" in row_text:
            listing_type = "Tender"
        else:
            listing_type = "Other"


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

        # 3) deadline (uses index)
        deadline = clean_text(tds[2].get_text(" ", strip=True)) if len(tds) > 2 else ""

        # 4) sector/services (uses index)
        focus_sector = clean_text(tds[3].get_text(" ", strip=True)) if len(tds) > 3 else ""

        # 5) geography (uses index)
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
            "type": listing_type,
            "title": title,
            "detail_page_url": detail_page_url,
            "donor_name": donor_name,
            "deadline": deadline,
            "focus_sector": focus_sector,
            "geographic_area": geographic_area,
            "ai_summary": ""
        })

    return results

#makes http get request
def fetch_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

#FILTER FOR KEYWORDS, TYPES, GEOGRAPHIES

WORKFORCE_KEYWORDS = [
    # Employment and Workforce
    "youth employment",
    "workforce development",
    "employability",
    "job placement",
    "job creation",
    "livelihoods",
    "economic empowerment",
    "economic inclusion",
    "apprenticeship",
    "internship",
    "mentorship",
    "job readiness",
    "job search",
    "labor market activation",
    "economic participation",
    "labor market entry",
    "NEET",
    "work readiness",
    "job seekers",
    "early-career",
    "access to opportunities",
    "reducing inequalities",

    # Skills and Training
    "skills development",
    "vocational training",
    "technical training",
    "soft skills",
    "digital skills",
    "vocational skills",
    "technical skills",
    "green jobs",
    "green skills",
    "TVET",
    "upskilling",
    "reskilling",
    "employability skills",
    "curriculum development",
    "vocational training center",
    "career center",
    "AI skills",
    "climate change",
    "financial literacy",
    "circular economy",
    "higher education",
    "university",
    "educational institutions",
    "life skills",
    "transversal skills",
    "entrepreneurial skills",
    "blended training",

    # Entrepreneurship and Private Sector
    "entrepreneurship",
    "SME development",
    "private sector development",
    "self employment",
    "virtual jobs",
    "income generation",
    "startup incubation",
    "employer engagement",
    "business acceleration",
    "micro entrepreneurship",
    "new business creation",
    "SME",
    "incubation",
    "green entrepreneurship",
    "women entrepreneurship",
    "startup",
    "startup support",
    "financial inclusion",
    "home-based businesses",
    "MSME",
    "microbusiness",
    "freelance",
    "gig work",
    "gig economy",

    # Systems Change
    "capacity building",
    "systems strengthening",
    "framework",
    "action plan",
    "competitiveness",
    "skills gaps",
    "business association",
    "chamber of commerce",
    "industry federation",
]

ALLOWED_TYPES = ["Tender", "Grant"]

ALLOWED_GEOGRAPHIES = [
    "morocco", "algeria", "tunisia", "egypt", "jordan", "palestine",
    "UAE", "united arab emirates", "saudi arabia", "lebanon",
    "bahrain", "syria", "mena"
]

def is_workforce_related(row):
    text = " ".join([
        row.get("type", ""),
        row.get("title", ""),
        row.get("detail_page_url", ""),
        row.get("donor_name", ""),
        row.get("deadline", ""),
        row.get("focus_sector", ""),
        row.get("geographic_area", ""),
    ]).lower()
    return any(keyword.lower() in text for keyword in WORKFORCE_KEYWORDS)

def is_allowed_type(row):
    return row.get("type", "") in ALLOWED_TYPES

def is_in_geography(row):
    text = row.get("geographic_area", "").lower()
    return any(geo in text for geo in ALLOWED_GEOGRAPHIES)

def apply_filters(df):
    df["filter_workforce"] = df.apply(is_workforce_related, axis=1)
    df["filter_type"]       = df.apply(is_allowed_type, axis=1)
    df["filter_geography"]  = df.apply(is_in_geography, axis=1)
    df["passes_all"]        = df["filter_workforce"] & df["filter_type"] & df["filter_geography"]
    return df


#RUNS THE ACTUAL CODE:

html = fetch_html(LISTING_URL)
listing_items = extract_listing_rows(html)

df = pd.DataFrame(listing_items)
#df with true or false value whether it matches a requirement
df = apply_filters(df)

#df with only the true values from above
df = df[df["passes_all"] == True]
# print(df.head())

#CONVERTING TO EXCEL SPREADSHEET
wb = Workbook()
ws = wb.active
ws.title = "Tenders & Grants"

# Header row
headers = ["Title", "Type","Donor Name", "Geographic Area", "Focus Sector", "Deadline", "Source Link", "Amount (USD)", "Eligibility"]
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
        row["type"],
        row["donor_name"],
        row["geographic_area"],
        row["focus_sector"],
        row["deadline"],
        row["detail_page_url"],
        "",  # Amount USD (cannot find so filler for now)
        ""   # Eligibility (cannot find so filler for now)
    ])

# Auto-fit column widths
# Auto-fit column widths based on content
for col in ws.columns:
    max_length = max(len(str(cell.value)) if cell.value else 0 for cell in col)
    adjusted_width = min(max_length + 4, 80)  # +4 padding, cap at 80
    ws.column_dimensions[col[0].column_letter].width = adjusted_width

# Freeze header row
ws.freeze_panes = "A2"

wb.save("tenders_grants.xlsx")
print("Saved to tenders_grants.xlsx")

# #TRYING TO EXACT FOR INDIVIDUAL PAGES
# def extract_detail_page(detail_url):
#     html = fetch_html(detail_url)
#     soup = BeautifulSoup(html, "html.parser")

#     # collect all links
#     links = []
#     for a in soup.find_all("a", href=True):
#         href = urljoin(detail_url, a["href"])
#         text = clean_text(a.get_text(" ", strip=True))
#         links.append({"text": text, "href": href})

#     # PDFs
#     pdf_links = [link["href"] for link in links if ".pdf" in link["href"].lower()]

#     # source/original link heuristics
#     source_link = ""
#     original_link = ""

#     for link in links:
#         text_lower = link["text"].lower()
#         href_lower = link["href"].lower()

#         if not source_link and ("source" in text_lower or "official" in text_lower):
#             source_link = link["href"]

#         if not original_link and ("original" in text_lower or "apply" in text_lower or "full notice" in text_lower):
#             original_link = link["href"]

#     # if there are no labeled links, try picking first non-darpe external link
#     external_links = [
#         link["href"] for link in links
#         if "darpe.me" not in link["href"]
#     ]

#     if not source_link and external_links:
#         source_link = external_links[0]

#     if not original_link and len(external_links) > 1:
#         original_link = external_links[1]

#     # description text
#     content_candidates = soup.select("article, .entry-content, .post-content, .content, .elementor-widget-container")
#     full_description = ""
#     if content_candidates:
#         full_description = clean_text(" ".join(c.get_text(" ", strip=True) for c in content_candidates))
#     else:
#         full_description = clean_text(soup.get_text(" ", strip=True))

#     return {
#         "pdf_links": pdf_links,
#         "source_link": source_link,
#         "original_link": original_link,
#         "full_description": full_description,
#     }
    
