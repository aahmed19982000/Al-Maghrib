import feedparser
from newspaper import Article

feed = feedparser.parse('https://arabic.rt.com/rss/sport/')
if feed.entries:
    first_link = feed.entries[0].link
    print("Link:", first_link)
    
    article = Article(first_link)
    article.download()
    article.parse()
    
    print("Title:", article.title)
    print("Image:", article.top_image)
    print("Text len:", len(article.text))
    print("Text snippet:", article.text[:100].replace('\n', ' '))
