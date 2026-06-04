import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.utils.text import slugify
from news.models import Article, Category
from django.contrib.auth.models import User
from django.utils import timezone
import random

class Command(BaseCommand):
    help = 'Import news from youm7.com for each section'

    def handle(self, *args, **kwargs):
        category_mapping = {
            'آخر الأخبار': 'https://www.youm7.com/Section/أخبار-عاجلة/65/1',
            'أخبار منوعة': 'https://www.youm7.com/Section/المرأة-والمنوعات/89/1',
            'اقتصاد': 'https://www.youm7.com/Section/اقتصاد-وبورصة/297/1',
            'تحليلات إقليمية': 'https://www.youm7.com/Section/أخبار-عربية/88/1',
            'تغطية الدول': 'https://www.youm7.com/Section/أخبار-عالمية/286/1',
            'ثقافة وتراث': 'https://www.youm7.com/Section/ثقافة/94/1',
            'رياضة': 'https://www.youm7.com/Section/أخبار-الرياضة/298/1',
            'Test Category': 'https://www.youm7.com/Section/منوعات/332/1', # fallback just in case
        }

        headers = {"User-Agent": "Mozilla/5.0"}
        author = User.objects.filter(is_superuser=True).first()
        if not author:
            author = User.objects.first()

        seen_urls = set()

        for cat in Category.objects.all():
            cat_name_ar = cat.name_ar if hasattr(cat, 'name_ar') and cat.name_ar else cat.name
            youm7_url = category_mapping.get(cat_name_ar)
            if not youm7_url:
                youm7_url = 'https://www.youm7.com/Section/أخبار-عاجلة/65/1'

            self.stdout.write(f"\nFetching section: {cat_name_ar} from {youm7_url}")
            
            resp = requests.get(youm7_url, headers=headers)
            if resp.status_code != 200:
                self.stdout.write(self.style.ERROR(f"Failed to fetch {youm7_url}"))
                continue
                
            soup = BeautifulSoup(resp.content, "html.parser")
            
            links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/story/' in href.lower():
                    link = "https://www.youm7.com" + href if href.startswith('/') else href
                    if link not in seen_urls and link not in links:
                        links.append(link)
                        
            # Keep top 15 unique ones for this category
            links = links[:15]
            
            if not links:
                self.stdout.write(self.style.WARNING(f"No links found for {cat_name_ar}!"))
                continue
                
            self.stdout.write(f"Found {len(links)} links. Starting import...")
            
            for i, link in enumerate(links):
                self.stdout.write(f"[{i+1}/{len(links)}] Fetching {link}...")
                seen_urls.add(link)
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
                    
                    content = article_soup.find('div', id='articleBody') or article_soup.find('div', class_='articleBody')
                    if not content:
                        paragraphs = article_soup.find_all('p')
                    else:
                        paragraphs = content.find_all('p')
                        
                    if not paragraphs:
                        self.stdout.write(self.style.WARNING("Could not find body, skipping."))
                        continue
                        
                    body_text = '\n\n'.join(p.text.strip() for p in paragraphs if p.text.strip())
                    if not body_text:
                        continue
                        
                    excerpt = paragraphs[0].text.strip()[:200] if paragraphs else body_text[:200]
                    
                    if Article.objects.filter(title_ar=title_text).exists() or Article.objects.filter(title=title_text).exists():
                        self.stdout.write(self.style.WARNING("Article already exists. Skipping."))
                        continue
                        
                    article = Article(
                        title=title_text,
                        slug=slugify(title_text, allow_unicode=True),
                        body=body_text,
                        excerpt=excerpt,
                        category=cat,
                        author=author,
                        status='published',
                        published_at=timezone.now(),
                        auto_translate=False,
                        is_featured=random.choice([True, False, False]), # 33% chance to be featured
                        is_breaking=random.choice([True, False, False, False]), # 25% chance to be breaking
                    )

                    if hasattr(article, 'title_ar'):
                        article.title_ar = title_text
                        article.title_en = title_text + " (English)"
                        article.body_ar = body_text
                        article.body_en = body_text + "\n(English Translation)"
                        article.excerpt_ar = excerpt
                        article.excerpt_en = excerpt
                    
                    base_slug = article.slug
                    counter = 1
                    while Article.objects.filter(slug=article.slug).exists():
                        article.slug = f"{base_slug}-{counter}"
                        counter += 1
                        
                    img_tag = article_soup.find('meta', property='og:image')
                    if img_tag and img_tag.get('content'):
                        img_url = img_tag['content']
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

