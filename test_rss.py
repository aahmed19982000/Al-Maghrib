import requests
from bs4 import BeautifulSoup

url = 'https://www.skynewsarabia.com/rss.xml'
res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(res.content, 'html.parser')
items = soup.find_all('item')[:3]
for item in items:
    print("Title:", item.title.text if item.title else "N/A")
    link_tag = item.find('link')
    link = link_tag.next_sibling if link_tag else None
    if not link:
        link = link_tag.text if link_tag else "N/A"
    else:
        link = str(link).strip()
    print("Link:", link)
    print("Category:", item.category.text if item.category else "N/A")
    print("-" * 20)
