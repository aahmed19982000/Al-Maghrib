import requests
from bs4 import BeautifulSoup

url = "https://www.addustour.com/"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers)
soup = BeautifulSoup(resp.content, "html.parser")

links = [a.get('href') for a in soup.find_all('a', href=True)]
print(links[:20])
