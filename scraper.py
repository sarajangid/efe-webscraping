import requests
from bs4 import BeautifulSoup
import time
import pandas as pd

BASE_SEARCH_URL = "https://simpler.grants.gov/search"
BASE_DOMAIN = "https://simpler.grants.gov"

params = {
    "andOr": "OR",
    "query": "education science technology engineering math career",
}

rows = []
links = []

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------
# STEP 1: Collect detail links using Selenium
# -----------------------------
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
driver.get(BASE_SEARCH_URL + "?andOr=OR&query=education+science+technology+engineering+math+career")

wait = WebDriverWait(driver, 10)

while True:
    # Wait until results load
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

    print(f"Collected {len(links)} links so far")

    # Try clicking Next
    try:
        next_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='pagination-next']"))
        )

        driver.execute_script("arguments[0].click();", next_button)
        time.sleep(2)

    except:
        print("No more pages.")
        break

driver.quit()


# -----------------------------
# STEP 2: Visit each grant page
# -----------------------------
for detail_link in links:

    try:
        response = requests.get(detail_link)
        soup = BeautifulSoup(response.text, "html.parser")

        # -----------------------------
        # Grant Name
        # -----------------------------
        title_tag = soup.select_one(
            "h2.margin-bottom-0.tablet-lg\\:font-sans-xl.desktop-lg\\:font-sans-2xl.margin-top-0"
        )
        grant_name = title_tag.get_text(strip=True) if title_tag else None

        # -----------------------------
        # Agency
        # -----------------------------
        agency = None
        p_tag = soup.select_one("p.usa-intro")
        if p_tag:
            agency = p_tag.get_text(strip=True).replace("Agency:", "").strip()

        # -----------------------------
        # Deadline
        # -----------------------------
        deadline = None
        for tag in soup.find_all("div", class_="usa-tag"):
            if "Closing:" in tag.get_text():
                span = tag.find("span")
                deadline = span.get_text(strip=True) if span else None
                break

        # -----------------------------
        # Awards
        # -----------------------------
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

        # -----------------------------
        # Description (adaptive logic)
        # -----------------------------
        description = None

        header = soup.find("h2", string=lambda x: x and "Description" in x)

        if header:
            div = header.find_next("div")

            if div:
                first_p = div.find("p")

                if first_p:
                    # Case 1: multiple <p> tags → use first one
                    description = first_p.get_text(strip=True)
                else:
                    # Case 2: no <p> tags → get full div text
                    description = div.get_text(strip=True)

        # -----------------------------
        # Documents
        # -----------------------------
        documents = [a["href"] for a in soup.select('tbody a.usa-link')]

        # -----------------------------
        # Application Link (Grants.gov)
        # -----------------------------
        application_link = None

        span = soup.find("span", string="View on Grants.gov")
        if span:
            parent_a = span.find_parent("a")
            if parent_a:
                application_link = parent_a.get("href")

        # -----------------------------
        # Append Row
        # -----------------------------
        rows.append({
            "Grant Name": grant_name,
            "Agency": agency,
            "Due Date": deadline,
            "Award Minimum": award_min,
            "Award Maximum": award_max,
            "Description": description,
            "Documents": documents,
            "Application Link": application_link
        })

        print(f"Scraped: {grant_name}")

        time.sleep(1)

    except Exception as e:
        print(f"Error scraping {detail_link}: {e}")
        continue


# -----------------------------
# STEP 3: Create DataFrame
# -----------------------------
df = pd.DataFrame(rows)

print(df.head())
print(f"Total grants scraped: {len(df)}")

# Optional: convert Documents list to JSON string for CSV
import json
df["Documents"] = df["Documents"].apply(json.dumps)

df.to_csv("grants.csv", index=False)

print("Saved to grants.csv")