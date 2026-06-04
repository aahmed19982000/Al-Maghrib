import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.utils.text import slugify
from news.models import Article, Category
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Import news from addustour.com'

    def handle(self, *args, **kwargs):
        self.stdout.write("Fetching homepage for links...")
        url = "https://www.addustour.com/"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers)
        soup = BeautifulSoup(resp.content, "html.parser")
        
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/articles/' in href and href not in links:
                links.append("https://www.addustour.com" + href if href.startswith('/') else href)
                
        links = links[:10]  # Get top 10 articles
        
        category, _ = Category.objects.get_or_create(name_ar="أخبار منوعة", name_en="General News", defaults={'slug': 'general-news'})
        author = User.objects.filter(is_superuser=True).first()
        if not author:
            author = User.objects.first()

        if not links:
            self.stdout.write(self.style.ERROR("No links found!"))
            return
            
        self.stdout.write(f"Found {len(links)} links. Starting import...")
        
        for i, link in enumerate(links):
            self.stdout.write(f"\n[{i+1}/{len(links)}] Fetching {link}...")
            try:
                r = requests.get(link, headers=headers, timeout=10)
                if r.status_code != 200:
                    self.stdout.write(self.style.ERROR(f"Failed to fetch {link} (Status {r.status_code})"))
                    continue
                    
                article_soup = BeautifulSoup(r.content, 'html.parser')
                
                title = article_soup.find('h1')
                if not title:
                    self.stdout.write(self.style.WARNING("Could not find title, skipping."))
                    continue
                title_text = title.text.strip()
                
                content = article_soup.find('div', id='post-content') or article_soup.find('div', class_='post-content') or article_soup.find('article') or article_soup.find('div', class_='article-body')
                if not content:
                    self.stdout.write(self.style.WARNING("Could not find body, skipping."))
                    continue
                    
                paragraphs = content.find_all('p')
                body_text = '\n\n'.join(p.text.strip() for p in paragraphs if p.text.strip())
                excerpt = paragraphs[0].text.strip()[:200] if paragraphs else body_text[:200]
                
                if Article.objects.filter(title_ar=title_text).exists():
                    self.stdout.write(self.style.WARNING("Article already exists. Skipping."))
                    continue
                    
                article = Article(
                    title_ar=title_text,
                    title_en=title_text + " (English)",
                    slug=slugify(title_text, allow_unicode=True),
                    body_ar=body_text,
                    body_en=body_text + "\n(English Translation)",
                    excerpt_ar=excerpt,
                    excerpt_en=excerpt,
                    category=category,
                    author=author,
                    status='published',
                    auto_translate=False
                )
                
                base_slug = article.slug
                counter = 1
                while Article.objects.filter(slug=article.slug).exists():
                    article.slug = f"{base_slug}-{counter}"
                    counter += 1
                    
                img_tag = article_soup.find('meta', property='og:image')
                if img_tag and img_tag.get('content'):
                    img_url = img_tag['content']
                    self.stdout.write(f"Downloading image: {img_url}")
                    img_r = requests.get(img_url, headers=headers, timeout=10)
                    if img_r.status_code == 200:
                        filename = img_url.split('/')[-1]
                        if '?' in filename:
                            filename = filename.split('?')[0]
                        if not filename.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                            filename += '.jpg'
                        article.cover_image.save(filename, ContentFile(img_r.content), save=False)
                
                article.save()
                self.stdout.write(self.style.SUCCESS(f"Successfully imported: {title_text}"))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error importing {link}: {str(e)}"))
