import requests

URL = "http://darpe.me/tenders-and-grants/"
page = requests.get(URL)

print(page.text)