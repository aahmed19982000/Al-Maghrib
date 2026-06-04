import requests
from bs4 import BeautifulSoup

url = "https://www.addustour.com/"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers)
soup = BeautifulSoup(resp.content, "html.parser")

links = set()
for a in soup.select('a[href*="/article/"]'):
    href = a.get('href')
    if href.startswith('http'):
        links.add(href)
    else:
        links.add("https://www.addustour.com" + href)

links = list(links)[:3]
print("Found links:", links)

for link in links:
    print(f"\nFetching {link}...")
    article_resp = requests.get(link, headers=headers)
    article_soup = BeautifulSoup(article_resp.content, "html.parser")
    
    title = article_soup.find('h1')
    title_text = title.text.strip() if title else "No Title"
    
    content_div = article_soup.find('div', class_='article-content') or article_soup.find('div', id='article-body') or article_soup.find('article')
    paragraphs = content_div.find_all('p') if content_div else []
    body = "\n".join([p.text.strip() for p in paragraphs if p.text.strip()])
    
    # Try to find image
    img = article_soup.find('meta', property='og:image')
    img_url = img['content'] if img else None
    
    print(f"Title: {title_text}")
    print(f"Image: {img_url}")
    print(f"Body snippet: {body[:200]}...")

