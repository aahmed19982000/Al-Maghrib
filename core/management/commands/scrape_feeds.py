import os
import time
import requests
import tempfile
import feedparser
from newspaper import Article as NewsArticle
from django.core.management.base import BaseCommand
from django.core.files import File
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from news.models import Article, Category
from core.models import HomePageCategory

User = get_user_model()

CATEGORY_FEEDS = {
    'اقتصاد': 'https://arabic.rt.com/rss/business/',
    'إقتصاد': 'https://arabic.rt.com/rss/business/',
    'رياضة': 'https://arabic.rt.com/rss/sport/',
    'ثقافة وتراث': 'https://arabic.rt.com/rss/culture/',
    'ثقافة و فنون': 'https://arabic.rt.com/rss/culture/',
    'تحليلات إقليمية': 'https://arabic.rt.com/rss/middle_east/',
    'تغطية الدول': 'https://arabic.rt.com/rss/world/',
    'آخر الأخبار': 'https://arabic.rt.com/rss/news/',
    'سياسة': 'https://arabic.rt.com/rss/news/',
}

class Command(BaseCommand):
    help = 'Scrape articles from RT Arabic RSS feeds using newspaper3k'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Clear existing articles')

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write(self.style.WARNING('Deleting all existing articles...'))
            for a in Article.all_objects.all():
                a.hard_delete()
            self.stdout.write(self.style.SUCCESS('Database cleared.'))

        author = User.objects.filter(is_superuser=True).first()
        if not author:
            self.stdout.write(self.style.ERROR('No superuser found.'))
            return

        # Scrape for each active homepage category
        home_categories = HomePageCategory.objects.filter(is_active=True)
        if not home_categories.exists():
            self.stdout.write(self.style.WARNING('No HomePageCategory found. Scraping standard categories.'))
            cats_to_scrape = ['اقتصاد', 'رياضة', 'ثقافة وتراث']
        else:
            cats_to_scrape = [hc.category.name for hc in home_categories]
            
        imported_total = 0
            
        for cat_name in cats_to_scrape:
            feed_url = CATEGORY_FEEDS.get(cat_name, 'https://arabic.rt.com/rss/news/')
            self.stdout.write(self.style.SUCCESS(f'\n--- Scraping Category: {cat_name} from {feed_url} ---'))
            
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                self.stdout.write(self.style.ERROR(f'Failed to parse feed for {cat_name}'))
                continue
                
            # Get category object
            db_cat, _ = Category.objects.get_or_create(
                name=cat_name,
                defaults={'slug': slugify(cat_name, allow_unicode=True) or f"cat-{int(time.time())}"}
            )
            
            # Scrape top 5
            entries = feed.entries[:5]
            for entry in entries:
                link = entry.link
                self.stdout.write(f'Parsing: {link}')
                
                try:
                    news_article = NewsArticle(link)
                    news_article.download()
                    news_article.parse()
                    
                    title = news_article.title or entry.title
                    body = news_article.text
                    
                    # Create excerpt (first 250 chars)
                    excerpt = body[:250] + '...' if len(body) > 250 else body
                    
                    if not title or not body:
                        self.stdout.write(self.style.WARNING('Skipping empty article'))
                        continue
                        
                    slug = slugify(title, allow_unicode=True)
                    if not slug:
                        slug = f"article-{int(time.time())}"
                        
                    # unique slug
                    orig_slug = slug
                    counter = 1
                    while Article.all_objects.filter(slug=slug).exists():
                        slug = f"{orig_slug}-{counter}"
                        counter += 1
                        
                    article = Article(
                        title_ar=title,
                        slug=slug,
                        excerpt_ar=excerpt,
                        body_ar=body,
                        author=author,
                        category=db_cat,
                        status='published',
                        auto_translate=True # Will translate on save
                    )
                    
                    # Handle image
                    img_url = news_article.top_image
                    if img_url:
                        img_res = requests.get(img_url, stream=True, timeout=10)
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
                            
                    self.stdout.write(f'Saving & Translating: {title}')
                    article.save()
                    imported_total += 1
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Error processing {link}: {e}'))
                    
        # Clear cache
        from django.core.cache import cache
        cache.clear()
        
        self.stdout.write(self.style.SUCCESS(f'\nSuccessfully imported {imported_total} articles across all categories.'))
