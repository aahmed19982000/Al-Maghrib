import os
import django
import sys
import random
import requests
import re
import time
import socket
from bs4 import BeautifulSoup

# Set global socket timeout to prevent indefinite hangs
socket.setdefaulttimeout(15)

# Set up Django environment
sys.path.append(os.path.abspath(os.path.dirname(__file__) + '/..'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "almaghrib.settings.dev")
django.setup()

from django.core.files.base import ContentFile
from django.utils.text import slugify
import feedparser
from django.contrib.auth.models import User
from news.models import Article, Category
from core.models import SiteSettings, HomePageSettings, HomePageCategory

def generate_unique_slug(title, model_class):
    slug = slugify(title, allow_unicode=True)
    if not slug:
        slug = f"article-{random.randint(1000, 9999)}"
    slug = slug[:200]
    original_slug = slug
    counter = 1
    while model_class.objects.filter(slug=slug).exists() or model_class.all_objects.filter(slug=slug).exists():
        slug = f"{original_slug}-{counter}"
        counter += 1
    return slug

def has_arabic_chars(text):
    if not text:
        return False
    return bool(re.search('[\u0600-\u06FF]', text))

def translate_with_retry(text, source='ar', target='en', max_retries=5, initial_delay=2):
    if not text or not text.strip():
        return text
    
    # Split text if it exceeds Google Translate's 5000 character limit
    MAX_CHARS = 4500
    if len(text) <= MAX_CHARS:
        chunks = [text]
    else:
        chunks = []
        current_chunk = ""
        for line in text.splitlines(keepends=True):
            if len(current_chunk) + len(line) > MAX_CHARS:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += line
        if current_chunk:
            chunks.append(current_chunk)
            
    translated_chunks = []
    for chunk in chunks:
        if not chunk.strip():
            translated_chunks.append(chunk)
            continue
            
        retries = 0
        delay = initial_delay
        success = False
        translated_chunk = chunk
        
        while retries < max_retries:
            try:
                # Add a sleep to prevent hitting limits
                time.sleep(0.5)
                from deep_translator import GoogleTranslator
                translator = GoogleTranslator(source=source, target=target)
                result = translator.translate(chunk)
                
                # Check that translation actually occurred (if source had Arabic, target should not have it)
                if result and (not has_arabic_chars(chunk) or not has_arabic_chars(result)):
                    translated_chunk = result
                    success = True
                    break
                else:
                    raise Exception("Translation output still contains Arabic characters.")
            except Exception as e:
                retries += 1
                print(f"  [Translation Retry {retries}/{max_retries}] Error: {e}. Sleeping {delay}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
                
        translated_chunks.append(translated_chunk)
        
    return "".join(translated_chunks)

def main():
    print("=== Starting Scrape and Seed Process ===")
    
    # 1. Select author
    author = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if not author:
        print("Error: No users found in database to assign as author!")
        return
    print(f"Using author: {author.username}")
    
    # 2. Deleting old articles and categories
    print("Deleting all existing articles and categories...")
    # hard_delete deletes from db bypassing soft delete
    deleted_articles = Article.objects.all_with_deleted().hard_delete()
    print(f"Deleted articles: {deleted_articles}")
    
    # Delete categories
    deleted_categories = Category.objects.all().delete()
    print(f"Deleted categories: {deleted_categories}")
    
    # 3. New Category definitions (Using updated, active RT Arabic RSS feeds)
    categories_def = [
        {
            'name_ar': 'سياسة', 'name_en': 'Politics', 'slug': 'politics',
            'color': '# rose', 'icon': 'gavel', 'order': 1,
            'rss': 'https://arabic.rt.com/rss/world/'
        },
        {
            'name_ar': 'اقتصاد', 'name_en': 'Economy', 'slug': 'economy',
            'color': '# green', 'icon': 'trending_up', 'order': 2,
            'rss': 'https://arabic.rt.com/rss/business/'
        },
        {
            'name_ar': 'ثقافة وتراث', 'name_en': 'Culture & Heritage', 'slug': 'culture',
            'color': '# amber', 'icon': 'menu_book', 'order': 3,
            'rss': 'https://arabic.rt.com/rss/culture/'
        },
        {
            'name_ar': 'رياضة', 'name_en': 'Sports', 'slug': 'sports',
            'color': '# blue', 'icon': 'sports_soccer', 'order': 4,
            'rss': 'https://arabic.rt.com/rss/sport/'
        },
        {
            'name_ar': 'علوم وتكنولوجيا', 'name_en': 'Science & Tech', 'slug': 'technology',
            'color': '# purple', 'icon': 'devices', 'order': 5,
            'rss': 'https://arabic.rt.com/rss/space/'
        },
        {
            'name_ar': 'أخبار منوعة', 'name_en': 'Various News', 'slug': 'various',
            'color': '# indigo', 'icon': 'dashboard', 'order': 6,
            'rss': 'https://arabic.rt.com/rss/middle_east/'
        },
        {
            'name_ar': 'آخر الأخبار', 'name_en': 'Latest News', 'slug': 'latest-news',
            'color': '# gray', 'icon': 'campaign', 'order': 7,
            'rss': 'https://arabic.rt.com/rss/'
        }
    ]
    
    # 4. Creating categories and scraping articles
    created_categories = []
    
    for cat in categories_def:
        print(f"\nCreating Category: {cat['name_ar']} ({cat['name_en']})...")
        cat_obj = Category.objects.create(
            name_ar=cat['name_ar'],
            name_en=cat['name_en'],
            slug=cat['slug'],
            color=cat['color'],
            icon=cat['icon'],
            order=cat['order'],
            is_active=True
        )
        created_categories.append(cat_obj)
        
        print(f"Scraping RSS feed: {cat['rss']}...")
        feed = None
        for r in range(3):
            try:
                feed = feedparser.parse(cat['rss'])
                if feed and hasattr(feed, 'entries') and len(feed.entries) > 0:
                    break
                print(f"  Empty feed response (try {r+1}/3), sleeping 3s...")
                time.sleep(3)
            except Exception as fe:
                print(f"  Error parsing feed (try {r+1}/3): {fe}. Sleeping 3s...")
                time.sleep(3)
                
        if not feed or not hasattr(feed, 'entries') or len(feed.entries) == 0:
            print(f"  Failed to fetch feed {cat['rss']} after 3 attempts. Skipping category.")
            continue
            
        entries = feed.entries
        print(f"Found {len(entries)} entries in RSS feed.")
        
        count = 0
        for entry in entries:
            if count >= 10:
                break
                
            link = entry.link
            print(f"[{count+1}/10] Fetching: {link}")
            
            try:
                # Download page with retries
                page_res = None
                for pr in range(3):
                    try:
                        page_res = requests.get(link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        if page_res.status_code == 200:
                            break
                        print(f"  HTTP {page_res.status_code} (try {pr+1}/3), sleeping 3s...")
                        time.sleep(3)
                    except Exception as pe:
                        print(f"  Download error (try {pr+1}/3): {pe}. Sleeping 3s...")
                        time.sleep(3)
                        
                if not page_res or page_res.status_code != 200:
                    print(f"  Failed to download page {link} after 3 attempts.")
                    continue
                    
                page_soup = BeautifulSoup(page_res.content, 'html.parser')
                
                # Title
                title = entry.title
                
                # Cover image
                img_url = None
                img_tag = page_soup.find('meta', property='og:image') or page_soup.find('meta', name='twitter:image')
                if img_tag:
                    img_url = img_tag.get('content')
                
                # Excerpt
                intro_div = page_soup.find('div', class_='main-article__intro-text')
                if intro_div:
                    excerpt_text = intro_div.text.strip()
                else:
                    excerpt_text = entry.summary[:200] if hasattr(entry, 'summary') else ""
                
                # Body HTML content (preserving formatting but decomposing read-more items)
                body_div = page_soup.find('div', class_='main-article__editor-content') or page_soup.find('div', class_='editor-content') or page_soup.find('div', class_='article__text')
                if body_div:
                    # Clean up unwanted tags (scripts, styles, advertising, read-more wrappers)
                    for tag in body_div(['script', 'style', 'iframe', 'ins', 'form', 'button', 'article', 'section']):
                        tag.decompose()
                    
                    # Sanitize tag attributes to preserve clean formatting but keep links/images
                    for tag in body_div.find_all(True):
                        allowed_attrs = {}
                        if tag.name == 'a' and tag.has_attr('href'):
                            allowed_attrs['href'] = tag['href']
                        if tag.name == 'img' and tag.has_attr('src'):
                            allowed_attrs['src'] = tag['src']
                        tag.attrs = allowed_attrs
                    
                    # Additional safeguard: delete tags with read-more keywords
                    for tag in body_div.find_all(True):
                        if tag == body_div:
                            continue
                        if not tag.parent:
                            continue
                        tag_text = tag.get_text().strip()
                        if any(phrase in tag_text for phrase in ['إقرأ المزيد', 'إقرأ أيضاً', 'اقرأ أيضاً', 'اقرأ أيضا', 'اقرأ المزيد']):
                            if len(tag_text) < 120:
                                tag.decompose()
                                
                    body_html = body_div.decode_contents().strip()
                else:
                    # Fallback to paragraph extraction
                    body_divs = page_soup.find_all('div', class_='main-article__editor-content')
                    if not body_divs:
                        body_divs = page_soup.find_all('div', class_='editor-content')
                    
                    if body_divs:
                        clean_divs = []
                        for bd in body_divs:
                            for tag in bd(['script', 'style', 'iframe', 'ins', 'form', 'button', 'article', 'section']):
                                tag.decompose()
                            for tag in bd.find_all(True):
                                if tag == bd:
                                    continue
                                if not tag.parent:
                                    continue
                                tag_text = tag.get_text().strip()
                                if any(phrase in tag_text for phrase in ['إقرأ المزيد', 'إقرأ أيضاً', 'اقرأ أيضاً', 'اقرأ أيضا', 'اقرأ المزيد']):
                                    if len(tag_text) < 120:
                                        tag.decompose()
                            clean_divs.append(bd.decode_contents().strip())
                        body_html = "".join(clean_divs)
                    else:
                        summary_text = entry.summary if hasattr(entry, 'summary') else ""
                        paragraphs = [f"<p>{p.strip()}</p>" for p in summary_text.split('\n') if p.strip()]
                        body_html = "".join(paragraphs)
                
                # Create Article object as draft (disabled auto_translate during save)
                article = Article(
                    title_ar=title,
                    body_ar=body_html,
                    excerpt_ar=excerpt_text,
                    category=cat_obj,
                    author=author,
                    status='draft',
                    auto_translate=False,
                    is_breaking=False,
                    is_featured=False
                )
                article.slug = generate_unique_slug(title, Article)
                
                # Translate manually with retries and exponential backoff
                print(f"  Translating title...")
                article.title_en = translate_with_retry(title)
                print(f"  Translating excerpt...")
                article.excerpt_en = translate_with_retry(excerpt_text)
                print(f"  Translating body...")
                article.body_en = translate_with_retry(body_html)
                
                # Populate SEO metadata
                from django.utils.html import strip_tags
                article.meta_title_ar = title
                article.meta_title_en = article.title_en
                article.meta_title = title
                
                desc_ar = strip_tags(excerpt_text or body_html)
                desc_ar = " ".join(desc_ar.split())[:160]
                article.meta_desc_ar = desc_ar
                article.meta_desc = desc_ar
                
                desc_en = strip_tags(article.excerpt_en or article.body_en)
                desc_en = " ".join(desc_en.split())[:160]
                article.meta_desc_en = desc_en
                
                # Save Cover image
                if img_url:
                    try:
                        img_res = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        if img_res.status_code == 200:
                            file_name = f"{article.slug}.jpg"
                            article.cover_image.save(file_name, ContentFile(img_res.content), save=False)
                    except Exception as e:
                        print(f"  Error downloading image: {e}")
                
                article.save()
                print(f"  Successfully saved article: {title[:50]}...")
                count += 1
                
                # Short pause between articles to avoid rate-limiting issues
                time.sleep(1.5)
                
            except Exception as e:
                print(f"  Error processing article {link}: {e}")
                continue
                
    # 5. Link Categories in Site Settings (Navbar/Footer)
    print("\nUpdating site settings navbar and footer categories...")
    site_settings = SiteSettings.load()
    site_settings.navbar_categories.clear()
    site_settings.footer_categories.clear()
    
    # Exclude latest-news from navbar
    navbar_cats = [c for c in created_categories if c.slug != 'latest-news']
    for cat in navbar_cats:
        site_settings.navbar_categories.add(cat)
        
    # Standard footer categories
    footer_slugs = ['politics', 'economy', 'culture', 'sports']
    for cat in created_categories:
        if cat.slug in footer_slugs:
            site_settings.footer_categories.add(cat)
            
    site_settings.save()
    print("Site settings updated.")
    
    # 6. HomePageCategory mapping
    print("\nUpdating homepage categories...")
    HomePageCategory.objects.all().delete()
    styles = ['featured_grid', 'mixed_grid', 'dark_cards', 'simple_cards', 'list', 'grid']
    
    for idx, cat in enumerate(navbar_cats):
        style = styles[idx % len(styles)]
        HomePageCategory.objects.create(
            category=cat,
            order=idx,
            design_style=style,
            article_count=4,
            is_active=True
        )
    print("Homepage categories updated.")
    print("\n=== Scrape and Seed Process Completed Successfully ===")

if __name__ == '__main__':
    main()
