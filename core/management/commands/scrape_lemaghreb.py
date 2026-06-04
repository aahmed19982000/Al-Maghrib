import os
import requests
import tempfile
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.core.files import File
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from news.models import Article, Category, Comment, Like, Bookmark
from dashboard.models import ActivityLog

User = get_user_model()

class Command(BaseCommand):
    help = 'Scrape articles from ar.lemaghreb.tn and import them'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=15, help='Number of articles to scrape')

    def handle(self, *args, **options):
        limit = options['limit']
        self.stdout.write(self.style.WARNING('Deleting all existing articles...'))
        
        # Delete existing data
        for article in Article.all_objects.all():
            article.hard_delete()
        
        self.stdout.write(self.style.SUCCESS('Database cleared. Starting scrape...'))
        
        # Get superuser to assign articles to
        author = User.objects.filter(is_superuser=True).first()
        if not author:
            self.stdout.write(self.style.ERROR('No superuser found to assign articles to.'))
            return
            
        base_url = 'https://ar.lemaghreb.tn/index.php'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8',
            'Connection': 'keep-alive'
        }
        
        import time
        try:
            res = requests.get(base_url, headers=headers, timeout=15)
            res.raise_for_status()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to fetch homepage: {e}'))
            return
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Find article links
        article_links = []
        for a in soup.select('a'):
            href = a.get('href')
            if href and '/item/' in href and href not in article_links:
                article_links.append(href)
                
        # Limit the number
        article_links = article_links[:limit]
        self.stdout.write(f'Found {len(article_links)} links. Processing...')
        
        imported_count = 0
        for link in article_links:
            # We want to use the domain without index.php for urls
            base_domain = 'https://ar.lemaghreb.tn/'
            full_url = urljoin(base_domain, link)
            self.stdout.write(f'Fetching: {full_url}')
            
            time.sleep(2)
            
            try:
                article_res = requests.get(full_url, headers=headers, timeout=10)
                article_res.raise_for_status()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to fetch {full_url}: {e}'))
                continue
                
            article_soup = BeautifulSoup(article_res.text, 'html.parser')
            
            # Extract title
            title_tag = article_soup.select_one('h1.itemTitle') or article_soup.select_one('h2.itemTitle')
            if not title_tag:
                self.stdout.write(self.style.WARNING('No title found, skipping.'))
                continue
            title = title_tag.text.strip()
            
            # Extract content
            intro_tag = article_soup.select_one('div.itemIntroText')
            excerpt = intro_tag.text.strip() if intro_tag else ''
            
            full_tag = article_soup.select_one('div.itemFullText')
            if not full_tag:
                # Sometimes it might just be the intro
                body = excerpt
            else:
                body = str(full_tag) # keep HTML for body
                
            if not body:
                continue
                
            # Determine category from URL path
            # /سياسة/المغرب-اليوم/item/...
            path_parts = unquote(link).strip('/').split('/')
            category_name = path_parts[0] if path_parts else 'آخر الأخبار'
            category_name = category_name.replace('-', ' ')
            
            # Map or create category
            cat, created = Category.objects.get_or_create(
                name=category_name,
                defaults={'slug': slugify(category_name, allow_unicode=True) or f"cat-{imported_count}"}
            )
            
            # Create article
            slug = slugify(title, allow_unicode=True)
            if not slug:
                slug = f"article-{imported_count}"
                
            # Ensure slug is unique
            original_slug = slug
            counter = 1
            while Article.all_objects.filter(slug=slug).exists():
                slug = f"{original_slug}-{counter}"
                counter += 1
                
            article = Article(
                title_ar=title,
                slug=slug,
                excerpt_ar=excerpt,
                body_ar=body,
                author=author,
                category=cat,
                status='published',
                auto_translate=True # Will trigger translation on save
            )
            
            # Handle image
            img_tag = article_soup.select_one('div.itemImageBlock img')
            if img_tag:
                img_src = img_tag.get('src') or img_tag.get('data-src')
                if img_src:
                    img_url = urljoin(base_url, img_src)
                    try:
                        img_res = requests.get(img_url, headers=headers, stream=True, timeout=10)
                        if img_res.status_code == 200:
                            lf = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                            for block in img_res.iter_content(1024 * 8):
                                if not block:
                                    break
                                lf.write(block)
                            lf.seek(0)
                            article.cover_image.save(f"{slug}.jpg", File(lf), save=False)
                            lf.close()
                            os.unlink(lf.name)
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'Failed to download image: {e}'))
            
            # Save article (this triggers auto translation and image optimization)
            self.stdout.write(f'Saving & Translating: {title}')
            try:
                article.save()
                imported_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to save article: {e}'))
                
        # Clear cache
        from django.core.cache import cache
        cache.clear()
        
        self.stdout.write(self.style.SUCCESS(f'Successfully imported {imported_count} articles.'))
