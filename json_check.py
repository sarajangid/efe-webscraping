import requests
from bs4 import BeautifulSoup
import json

# 1. Fetch the HTML content
url = 'https://darpe.me/tenders-and-grants/'
response = requests.get(url)
soup = BeautifulSoup(response.content, 'html.parser')

# 2. Find the script tag containing the JSON data
# This often uses a specific type attribute or an ID
script_tag = soup.find('script', type='application/ld+json')

if script_tag:
    # 3. Extract the text content and parse it with the json module
    json_data = json.loads(script_tag.text)
    print(json_data)
else:
    print("No relevant JSON script tag found.")

# Another method: getting JSON from an input tag's value attribute
# input_tag = soup.find('input', id='init-data')
# if input_tag:
#     json_data = json.loads(input_tag['value'])
#     print(json_data)
