import requests
from bs4 import BeautifulSoup

url = 'https://ar.lemaghreb.tn/%D8%B3%D9%8A%D8%A7%D8%B3%D8%A9/%D8%A7%D9%84%D9%85%D8%BA%D8%B1%D8%A8-%D8%A7%D9%84%D9%8A%D9%88%D9%85/item/120351-%D8%A7%D9%84%D8%AC%D9%85%D8%B9%D9%8A%D8%A9-%D8%A7%D9%84%D8%AA%D9%88%D9%86%D8%B3%D9%8A%D8%A9-%D9%84%D9%84%D8%A3%D9%88%D9%84%D9%8A%D8%A7%D8%A1-%D9%88%D8%A7%D9%84%D8%AA%D9%84%D8%A7%D9%85%D9%8A%D8%B0-%D8%AA%D8%AD%D8%B0%D9%91%D8%B1-%D9%85%D9%86-%D8%A7%D9%84%D8%AA%D8%B4%D9%83%D9%8A%D9%83-%D9%81%D9%8A-%D9%86%D8%B2%D8%A7%D9%87%D8%A9-%D8%A7%D9%85%D8%AA%D8%AD%D8%A7%D9%86-%D8%A7%D9%84%D8%A8%D9%83%D8%A7%D9%84%D9%88%D8%B1%D9%8A%D8%A7'
res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(res.text, 'html.parser')

title = soup.select_one('h1.itemTitle')
print("Title:", title.text.strip() if title else "NOT FOUND")

cat = soup.select_one('.itemCategory a')
if not cat:
    # try breadcrumbs
    cat = soup.select('.pathway a')
    cat = cat[-1].text.strip() if cat else "NOT FOUND"
print("Category:", cat)

img = soup.select_one('div.itemImageBlock img')
if img:
    print("Image:", img.get('src') or img.get('data-src'))
else:
    print("Image: NOT FOUND")

intro = soup.select_one('div.itemIntroText')
full = soup.select_one('div.itemFullText')

print("Intro:", intro.text.strip()[:50] if intro else "NOT FOUND")
print("Full:", full.text.strip()[:50] if full else "NOT FOUND")
