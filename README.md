# SAM.gov Grants Scraper

The script requests the SAM.gov CFDA (Assistance Listings) search results for the keyword “grants,” parses the response with BeautifulSoup (bs4)—either from the raw HTML (via `requests` or, for JS-rendered content, from the DOM after loading the page with Selenium) or from the SAM.gov API when an API key is supplied—and optionally visits each listing’s detail page to extract **geographic area** (country or region, e.g. MENA), **youth generation** (whether the program targets youth), **PDFs** (links to PDF documents), **brief summary**, **deadline**, and **link**. Results can be written to a CSV file and/or appended to a Google Sheet.

## Appending to Google Sheets

To append scraped data to the [EFE Web Scraper Google Sheet](https://docs.google.com/spreadsheets/d/1uV-a5J-7FFS9tHBBhvr7lOJ0RfBKIc_fFHWn3wTfSjY/edit?usp=sharing):

1. **Install** the Google dependencies: `pip install gspread google-auth`
2. **Create a Google Cloud service account** (Google Cloud Console → IAM & Admin → Service Accounts → Create). Download its JSON key.
3. **Enable the Google Sheets API** for the project (APIs & Services → Enable APIs → Google Sheets API).
4. **Share the Google Sheet** with the service account email (e.g. `your-sa@project.iam.gserviceaccount.com`) as Editor.
5. **Run the scraper** with Google Sheet append:
   - `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your-service-account.json`
   - `python sam_grants_scraper.py --google-sheet`
   - Or pass the sheet explicitly: `python sam_grants_scraper.py --google-sheet "https://docs.google.com/spreadsheets/d/1uV-a5J-7FFS9tHBBhvr7lOJ0RfBKIc_fFHWn3wTfSjY/edit" --credentials /path/to/key.json`

If the sheet is empty, the first run adds a header row, then appends all scraped rows. Later runs only append new data rows.
