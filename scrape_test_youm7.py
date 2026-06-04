import requests
from bs4 import BeautifulSoup

def test_scrape():
    url = "https://www.youm7.com/Section/اقتصاد/297"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.content, "html.parser")
    
    links = []
    # In youm7, articles are typically under something with class "col-xs-12"
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/story/' in href.lower() or '/News/' in href:
            full_link = "https://www.youm7.com" + href if href.startswith('/') else href
            if full_link not in links:
                links.append(full_link)
                
    print(f"Found {len(links)} links on {url}")
    print(links[:3])
    
    # fetch one
    if links:
        r2 = requests.get(links[0], headers=headers)
        s2 = BeautifulSoup(r2.content, "html.parser")
        
        # title
        title = s2.find('h1')
        print("Title:", title.text.strip() if title else "None")
        
        # content
        article_body = s2.find('div', id='articleBody') or s2.find('div', class_='articleBody')
        if article_body:
            ps = article_body.find_all('p')
            print("Body snippets:", [p.text.strip() for p in ps[:2]])
            
        # image
        img = s2.find('meta', property='og:image')
        print("Image:", img['content'] if img else "None")

if __name__ == '__main__':
    test_scrape()
