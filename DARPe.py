import requests
from bs4 import BeautifulSoup

URL = "http://darpe.me/tenders-and-grants/"
page = requests.get(URL)
# print(page.text)
soup = BeautifulSoup(page.content, "html.parser")

grant_cards = soup.find("td", style="border-right:0px")
print(grant_cards.prettify())