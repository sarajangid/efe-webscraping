def run_scraper():
    # Example scraping logic
    import requests
    from bs4 import BeautifulSoup
    
    url = "https://example.com"
    response = requests.get(url)    
    soup = BeautifulSoup(response.text, "html.parser")
    
    return soup.title.text