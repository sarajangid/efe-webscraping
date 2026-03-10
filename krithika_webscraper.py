# pip install selenium
# pip install selenium

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import re
import csv
import os

url = "https://impactfunding.substack.com/s/education-human-rights-and-inclusion/archive?sort=new"

options = Options()
options.add_argument("--headless")
driver = webdriver.Chrome(options=options)

MENA_COUNTRIES = [
    "Morocco", "Algeria", "Tunisia", "Egypt", "Jordan",
    "Palestine", "Yemen", "UAE", "United Arab Emirates",
    "Saudi Arabia", "Lebanon", "Bahrain", "Qatar",
    "Oman", "Kuwait", "Iraq", "Iran", "Libya", "Syria"
]

def is_mena(geography):
    if geography:
        return any(country.lower() in geography.lower() for country in MENA_COUNTRIES)
    return False

def has_youth_focus(text):
    groups = {
        "youth": "Youth",
        "young people": "Young People",
        "young": "Young People",
        "students": "Students",
        "student": "Students",
        "children": "Children",
        "child": "Children",
        "adolescents": "Adolescents",
        "adolescent": "Adolescents",
        "teens": "Teens",
        "teen": "Teens"
    }

    text = text.lower()
    found_groups = set()

    for keyword, label in groups.items():
        if keyword in text:
            found_groups.add(label)

    if found_groups:
        return "; ".join(sorted(found_groups))

    return "None"


def extract_field(label, text):
    pattern = rf"{label}:\s*(.*)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None

results = []
try:
    driver.get(url)

    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/p/']"))
    )

    time.sleep(2)

    articles = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")
    article_links = list(set([a.get_attribute("href") for a in articles if a.get_attribute("href")]))

    print(f"\nFound {len(article_links)} articles\n") # unnecessary

    for link in article_links:

        driver.get(link)
        time.sleep(3)

        article_text = driver.find_element(By.TAG_NAME, "article").text

        # Split into grants using "Geographies:"
        parts = article_text.split("Geographies:")

        for part in parts[1:]:

            block = "Geographies:" + part

            geo_index = article_text.find(block)

            title = ""
            summary = ""

            if geo_index != -1:
                before_text = article_text[:geo_index].strip()
                paragraphs = before_text.split("\n")

                if len(paragraphs) >= 2:
                    summary = paragraphs[-1].strip()
                    title = paragraphs[-2].strip()

            geography = extract_field("Geographies", block)
            deadline = extract_field("Deadline", block)

            if geography and is_mena(geography):

                youth = has_youth_focus(block)

                # Find the summary text right before this "Geographies:"
                summary = ""

                geo_index = article_text.find(block)

                if geo_index != -1:
                    before_text = article_text[:geo_index].strip()
                    paragraphs = before_text.split("\n")
                    
                    # last non-empty line before Geographies
                    for line in reversed(paragraphs):
                        if line.strip():
                            summary = line.strip()
                            break

                # PDF links (from whole article — safe fallback)
                pdf_links = []
                links_in_article = driver.find_elements(By.CSS_SELECTOR, "a[href$='.pdf']")
                for l in links_in_article:
                    pdf_links.append(l.get_attribute("href"))

                results.append({
                    "Grant Name": title,
                    "Geographic Area": geography,
                    "Youth Focus": youth,
                    "PDF Links": ", ".join(pdf_links) if pdf_links else "",
                    "Brief Summary": summary,
                    "Deadline": deadline,
                    "Source Link": link
                })

finally:
    driver.quit()

filename = os.path.join(os.path.expanduser("~"), "Downloads", "test6.csv") # change this

with open(filename, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "Grant Name",
            "Geographic Area",
            "Youth Focus",
            "PDF Links",
            "Brief Summary",
            "Deadline",
            "Source Link"
        ]
    )

    writer.writeheader()
    writer.writerows(results)

print(f"\nCSV saved to: {filename}")
