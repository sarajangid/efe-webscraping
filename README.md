# MENA Grant Scraper

Automated web scraping toolkit for discovering grant opportunities focused on **MENA region** youth employment and workforce development.

## Overview

This codebase scrapes multiple grant databases to find funding opportunities matching:
- **Geographic focus**: MENA countries (Morocco, Algeria, Tunisia, Egypt, Jordan, Palestine, Gaza, Yemen, UAE, Saudi Arabia, Lebanon, Bahrain, Syria)
- **Thematic focus**: Youth employment, workforce development, entrepreneurship, SME development, vocational training, green jobs, digital skills, financial inclusion

## Quick Start

### Prerequisites

- Python 3.8 or higher
- Google Chrome or Chromium installed
- Gemini API key (for AI summaries)

### Setup

1. **Clone and setup virtual environment:**
   ```bash
   cd efe-webscraping
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers:**
   ```bash
   playwright install
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env  # Or edit .env directly
   # Edit .env with your API keys and settings
   ```

## Environment Configuration

Edit `.env` with your credentials:

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Google Gemini API key for AI summaries | `AIzaSy...` |
| `EXCEL_FILE` | Output Excel filename | `Grants.xlsx` |

### Optional Variables (SharePoint/OneDrive)

| Variable | Description | Example |
|----------|-------------|---------|
| `CLIENT_ID` | Microsoft Azure app client ID | `abc123...` |
| `CLIENT_SECRET` | Microsoft Azure app client secret | `xyz789...` |
| `TENANT_ID` | Microsoft Azure tenant ID | `tenant-uuid` |
| `SITE_ID` | SharePoint site ID | `site-uuid` |
| `ONEDRIVE_FOLDER` | OneDrive folder for uploads | `Grants` |
| `BASE_DOWNLOAD_DIR` | Local download directory | `Grants` |

## Scrapers

### 1. SAM.gov Scraper (`sam.py`)

**Source**: U.S. federal government grant database
**Focus**: Grants, cooperative agreements, solicitations

```bash
python sam.py
```

**Features:**
- Uses Selenium with rotating driver pool (10 workers)
- Searches by keywords across multiple pages
- Parallel scraping with ThreadPoolExecutor
- Batch AI summary generation

**Output sheet**: `sam`

### 2. DevelopmentAid MENA Scraper (`dev_aid.py`)

**Source**: DevelopmentAid.org
**Focus**: International development grants

```bash
python dev_aid.py --pages 10 --headless
```

**Arguments:**
- `--pages`: Number of SERP pages to scrape (default: 10)
- `--headless`: Run browser without GUI

**Features:**
- Uses Playwright
- Filters by MENA countries + keyword matching
- Batch AI summary generation

**Output sheet**: `dev_aid`

### 3. EU Commission Scraper (`eu_comm.py`)

**Source**: DevelopmentAid EU Commission tenders
**Focus**: EU-funded grants

```bash
python eu_comm.py --pages 10 --headless
```

**Arguments:**
- `--pages`: Number of SERP pages to scrape
- `--headless`: Run headless

**Features:**
- Uses Playwright
- Similar filtering logic to dev_aid
- Batch AI summary generation

**Output sheet**: `eu_comm`

### 4. FundsforNGOs Scraper (`fundsforngos_webscraper.py`)

**Source**: FundsforNGOs.org
**Focus**: Grants for NGOs and civil society

```bash
python fundsforngos_webscraper.py
```

**Features:**
- Uses requests + BeautifulSoup
- No JavaScript rendering required
- Lightweight, fast execution

**Output sheet**: `fundsforngimak

### 5. Impact Funding Scraper (`impact_funding_scraper.py`)

**Source**: Impact funding databases
**Focus**: Social impact and development funding

```bash
python impact_funding_scraper.py
```

**Features:**
- Uses Google Gemini API for data extraction
- Requires `.env` configuration

**Output sheet**: `impact_funding`

## Output Format

All scrapers append to a single Excel file (`Grants.xlsx` by default) with separate sheets:

| Sheet Name | Source |
|------------|--------|
| `sam` | SAM.gov |
| `dev_aid` | DevelopmentAid |
| `eu_comm` | EU Commission |
| `fundsforngos` | FundsforNGOs |
| `impact_funding` | Impact Funding |

### Columns

Each row contains:
- **Opportunity ID**: Unique identifier
- **Opportunity Type**: Grant/Solicitation/Notice type
- **Title**: Opportunity title
- **Donor Name**: Funding organization
- **Geographic Area**: Matched MENA countries
- **Focus / Sector**: Inferred sector from keywords
- **Application Deadline**: Closing date
- **Amount Min/Max (USD)**: Funding range
- **Eligibility**: Eligible applicant types
- **Matched Keywords**: Filtered keywords
- **Source Link**: Original listing URL
- **Original Link**: External application link (if available)
- **Date Posted**: Publication date
- **Date Scraped**: Scrape timestamp
- **AI Summary**: Gemini-generated summary

## AI Summary Feature

All scrapers include optional AI-generated summaries using Google Gemini API.

### How It Works

1. **During scraping**: Raw fields extracted to temporary `_opp_data` field
2. **After filtering**: Batch generation for only filtered/kept results
3. **Cleanup**: Temporary field removed before saving

### Rate Limit Optimization

The batch approach prevents Gemini API rate limit errors:
- Only generates summaries for **final filtered results** (not every checked opportunity)
- Processes summaries **after** MENA + keyword filtering complete
- Reduces API calls by 10-100x depending on filter selectivity

### Example

If 500 opportunities are checked but only 25 pass filters:
- **Old approach**: 500 API calls (hits rate limit)
- **Batch approach**: 25 API calls (no rate limit issues)

## Workflow

```
1. Configure .env with API keys
2. Activate virtual environment: source venv/bin/activate
3. Run scrapers: python <scraper.py> [options]
4. Monitor console for progress and filtering stats
5. Access results in Grants.xlsx
```

## Architecture

```
┌─────────────────────────────────────────┐
│         Scraper Entry Point             │
│  (sam.py | dev_aid.py | eu_comm.py)     │
└─────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│      Browser Automation                 │
│   (Selenium / Playwright / Requests)    │
└─────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│         Filter Pipeline                 │
│  1. MENA country matching               │
│  2. Keyword matching                    │
│  3. Grant type filtering                │
└─────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│       Field Extraction                  │
│  Title, Donor, Geography, Sector, etc.  │
└─────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│    Batch AI Summary Generation          │
│  (Only for filtered results, not all)   │
└─────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│       Excel Output (Multi-Sheet)        │
└─────────────────────────────────────────┘
```

## Dependencies

Install with:
```bash
pip install -r requirements.txt
```

**Packages:**
- **Web Scraping**: requests, beautifulsoup4, selenium, webdriver-manager, playwright
- **Data Processing**: pandas, openpyxl
- **AI/ML**: google-genai
- **Environment**: python-dotenv
- **Utilities**: urllib3

## Troubleshooting

### Common Issues

**1. Gemini rate limit (429 error)**
```
429 Too Many Requests
```
- **Solution**: Batch generation is already implemented. If still hitting limits:
  - Reduce `--pages` argument
  - Add delays between API calls in code
  - Check Gemini API quota in Google Cloud Console

**2. Missing GEMINI_API_KEY**
```
KeyError: 'GEMINI_API_KEY'
```
- **Solution**: Ensure `.env` contains: `GEMINI_API_KEY=your_key`
- Verify `.env` is loaded: `print(os.environ.get("GEMINI_API_KEY"))`

**3. Playwright timeout**
```
TimeoutError: Timeout 30000ms exceeded
```
- **Solution**:
  - Increase timeout in code
  - Use `--headless` mode
  - Check network/connection

**4. Selenium Chrome error**
```
WebDriverException: Chrome failed to start
```
- **Solution**:
  - Install Chrome/Chromium
  - Run `webdriver-manager` to update drivers
  - Check PATH for chromedriver

**5. Excel file locked**
```
PermissionError: [Errno 13] Permission denied
```
- **Solution**: Close Excel file if open in another program

### Debug Mode

Run with Python debugger:
```bash
python -m pdb sam.py
```

Or add verbose logging in code.

## Contributing

1. Fork the repository
2. Create feature branch
3. Test with sample data
4. Submit pull request

## License

MIT License

---

**Note**: This toolkit is for authorized grant research and development purposes only. Respect website terms of service and robots.txt when scraping.