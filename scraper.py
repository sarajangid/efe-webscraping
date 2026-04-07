import datetime
import os
import re
import json
import time
import shutil
import requests
import pandas as pd
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from upload_to_sharepoint import download_documents
from summarizer import generate_simpler_summary

load_dotenv()
EXCEL_FILE=os.environ["EXCEL_FILE"]
BASE_DOWNLOAD_DIR = os.environ["BASE_DOWNLOAD_DIR"]


############################
# CONFIG
############################

BASE_SEARCH_URL = "https://simpler.grants.gov/search"
BASE_DOMAIN = "https://simpler.grants.gov"

params = {
    "andOr": "OR",
    "query": "education science technology engineering math career",
}

SHEET_NAME = "SimplerGrants"

os.makedirs(os.path.join(BASE_DOWNLOAD_DIR,SHEET_NAME), exist_ok=True)


############################
# COLLECT SEARCH LINKS
############################

search_url = BASE_SEARCH_URL + "?" + urlencode(params)

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
driver.get(search_url)

wait = WebDriverWait(driver, 10)

rows = []
links = []

while True:

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr.border-base")))

    soup = BeautifulSoup(driver.page_source, "html.parser")
    results = soup.select("tr.border-base")

    for result in results:

        a_tag = result.select_one("a")

        if not a_tag:
            continue

        relative_link = a_tag.get("href")
        full_link = BASE_DOMAIN + relative_link

        if full_link not in links:
            links.append(full_link)

    print(f"Collected {len(links)} links")

    try:

        next_button = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[data-testid='pagination-next']")
            )
        )

        driver.execute_script("arguments[0].click();", next_button)
        time.sleep(2)

    except:
        print("No more pages")
        break

driver.quit()

'''wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tr.border-base")))

soup = BeautifulSoup(driver.page_source, "html.parser")
results = soup.select("tr.border-base")

for result in results:
    a_tag = result.select_one("a")
    if not a_tag:
        continue

    relative_link = a_tag.get("href")
    full_link = BASE_DOMAIN + relative_link

    if full_link not in links:
        links.append(full_link)

print(f"Collected {len(links)} links from first page")

driver.quit()'''


############################
# SCRAPE DETAILS
############################

for detail_link in links:

    try:
        response = requests.get(detail_link)
        soup = BeautifulSoup(response.text, "html.parser")

        title_tag = soup.select_one(
            "h2"
        )
        grant_name = title_tag.get_text(strip=True) if title_tag else None

        agency = None
        p_tag = soup.select_one("p.usa-intro")
        if p_tag:
            agency = p_tag.get_text(strip=True).replace("Agency:", "").strip()

        deadline = None
        for tag in soup.find_all("div", class_="usa-tag"):
            if "Closing:" in tag.get_text():
                span = tag.find("span")
                deadline = span.get_text(strip=True) if span else None
                break

        award_min = 0
        award_max = 0

        blocks = soup.select('div[data-testid="grid"]')

        for block in blocks:
            value_tag = block.select_one("p.font-sans-sm.text-bold")
            label_tag = block.select_one("p.desktop-lg\\:font-sans-sm")

            if not value_tag or not label_tag:
                continue

            value_text = value_tag.get_text(strip=True)
            label_text = label_tag.get_text(strip=True)

            try:
                numeric_value = int(
                    value_text.replace("$", "").replace(",", "").strip()
                )
            except ValueError:
                numeric_value = 0

            if "Minimum" in label_text:
                award_min = numeric_value
            elif "Maximum" in label_text:
                award_max = numeric_value

        description = None

        header = soup.find("h2", string=lambda x: x and "Description" in x)

        # Filter: keep only descriptions that mention at least 3 of the target phrases
        target_phrases = [
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
            "neet",
            "work readiness",
            "job seekers",
            "early-career",
            "access to opportunities",
            "reducing inequalities",
            "skills development",
            "vocational training",
            "technical training",
            "soft skills",
            "digital skills",
            "vocational skills",
            "technical skills",
            "green jobs",
            "green skills",
            "tvet",
            "upskilling",
            "reskilling",
            "employability skills",
            "curriculum development",
            "vocational training center",
            "career center",
            "ai skills",
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
            "entrepreneurship",
            "sme development",
            "private sector development",
            "self employment",
            "virtual jobs",
            "income generation",
            "startup incubation",
            "employer engagement",
            "business acceleration",
            "micro entrepreneurship",
            "new business creation",
            "sme",
            "incubation",
            "green entreprenurship",
            "women entrepreneurship",
            "startup",
            "startup support",
            "financial inclusion",
            "home-based businesses",
            "msme",
            "microbusiness",
            "freelance",
            "gig work",
            "gig economy",
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

        documents = [a["href"] for a in soup.select('tbody a.usa-link')]

        application_link = None

        span = soup.find("span", string="View on Grants.gov")
        if span:
            parent_a = span.find_parent("a")
            if parent_a:
                application_link = parent_a.get("href")

        if header:
            div = header.find_next("div")

            if div:
                text = div.get_text(separator="\n", strip=True)
                first_p = div.find("p")
                if first_p:
                    # Case 1: multiple <p> tags → use first one
                    description = first_p.get_text(strip=True)

                else:
                    # Case 2: no <p> tags → get full div text
                    description = div.get_text(strip=True)

                description_text = (text or "").lower()
                match_count = sum(1 for phrase in target_phrases if phrase in description_text)

                if match_count >= 1:

                    ai_summary = generate_simpler_summary(description)

                    rows.append({
                        "Date Scraped": datetime.datetime.now().strftime("%Y-%m-%d"),
                        "Grant Name": grant_name,
                        "Agency": agency,
                        "Due Date": deadline,
                        "Award Minimum": award_min,
                        "Award Maximum": award_max,
                        "Description": description,
                        "Documents": documents,
                        "Application Link": application_link,
                        "AI Summary": ai_summary
                    })

        print(f"Scraped: {grant_name}")

        time.sleep(1)

    except Exception as e:
        print("Error scraping:", e)


############################
# DATAFRAME
############################

df = pd.DataFrame(rows)

df["Documents"] = df["Documents"].apply(json.dumps)


############################
# UPDATE EXCEL (UNCHANGED)
############################

if os.path.exists(EXCEL_FILE):
    existing_sheets = pd.ExcelFile(EXCEL_FILE).sheet_names

    if SHEET_NAME in existing_sheets:
        existing_df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
        existing_links = set(existing_df["Application Link"])
        new_rows = df[~df["Application Link"].isin(existing_links)]

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


############################
# SINGLE CALL TO PIPELINE
############################

download_documents(
    rows=rows,
    BASE_DOWNLOAD_DIR=os.path.join(BASE_DOWNLOAD_DIR,SHEET_NAME),
    BASE_DOMAIN=BASE_DOMAIN,
    grant_name_col="Grant Name",
    docs_arr_col="Documents"
)