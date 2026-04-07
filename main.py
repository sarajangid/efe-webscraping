import subprocess

from upload_to_sharepoint import process_uploads

scrapers = ["attempt2.py", "scraper.py", "impact_funding_scraper.py", "dev_aid_wo_playwright.py", "eu_comm_wo_playwright.py", "fundsforngos_webscraper.py", "sam_fast_wo_playwright.py"] # change to test later

try:
    for scraper in scrapers:
        try:
            result = subprocess.run(["python", scraper], check=True)
            print(f"{scraper} success")
        except subprocess.CalledProcessError as e:
            print(f":x: {scraper} failed with exit code {e.returncode} — continuing...")
        except Exception as e:
            print(f":x: {scraper} crashed: {e} — continuing...")
    #call upload to sharepoint here
    process_uploads()
    print("Uploaded to Sharepoint Successfully")
except Exception as e:
    print("Error uploading to sharepoint: ", {e})