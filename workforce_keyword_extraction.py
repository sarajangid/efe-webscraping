import pandas as pd

def load_keywords_from_excel(filepath):
    df = pd.read_excel(filepath)
    keywords = df.iloc[:, 1].dropna().str.strip().tolist() 
    return keywords

WORKFORCE_KEYWORDS = load_keywords_from_excel("/Users/jennifer/Downloads/Keywords for Scraper.xlsx")

print(WORKFORCE_KEYWORDS)