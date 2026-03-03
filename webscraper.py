#pip install selenium 
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

url = "https://impactfunding.substack.com/s/education-human-rights-and-inclusion/archive?sort=new"

# Setup Chrome options
options = Options()
options.add_argument("--headless") 
options.add_argument("--start-maximized")

driver = webdriver.Chrome(options=options)

try:
    driver.get(url)

    # Wait until article links load
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/p/']"))
    )

    # Give extra time for dynamic content
    time.sleep(2)

    articles = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")

    seen = set()

    print("\nFound " + str(len(articles)//2) + " Articles:\n")

    for article in articles:
        href = article.get_attribute("href")
        title = article.text.strip()

        if href and href not in seen and title:
            seen.add(href)
            print(title)
            print(href)
            print("-" * 50)

finally:
    driver.quit()
