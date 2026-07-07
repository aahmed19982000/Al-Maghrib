import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from django.utils import timezone
from django.core.files.base import ContentFile
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.conf import settings
from .models import Article, Category, AISettings, AISource, AIImportLog, WordPressSite

logger = logging.getLogger(__name__)

def call_gemini_api(prompt, api_key=None):
    """
    Calls the Gemini API directly using requests REST call.
    Uses Gemini 1.5 Flash. Returns JSON parsed response or None.
    """
    if not api_key:
        ai_settings = AISettings.get_settings()
        api_key = ai_settings.gemini_api_key or getattr(settings, 'GEMINI_API_KEY', None)
        
    if not api_key:
        logger.error("Gemini API key is not configured.")
        raise ValueError("Gemini API Key missing.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    # Request JSON to output standard structured data
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Extract response text
        candidates = data.get("candidates", [])
        if candidates:
            text_response = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return text_response
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        if 'response' in locals():
            logger.error(f"Response: {response.text}")
    return None


def fetch_news_items_from_source(source_url):
    """
    Fetches news items from an RSS feed or webpage.
    Returns a list of dictionaries with keys: 'title', 'link', 'description', 'image_url', 'guid'.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    items = []
    
    try:
        response = requests.get(source_url, headers=headers, timeout=15)
        response.raise_for_status()
        content = response.content
        
        soup = BeautifulSoup(content, 'xml')
        channel_items = soup.find_all('item')
        
        if channel_items:
            # RSS format
            for item in channel_items:
                title = item.find('title')
                link = item.find('link')
                desc = item.find('description')
                guid = item.find('guid')
                
                title_text = title.text.strip() if title else ""
                link_text = link.text.strip() if link else ""
                desc_text = desc.text.strip() if desc else ""
                guid_text = guid.text.strip() if guid else link_text
                
                # Try to find image URL in RSS media tags
                image_url = ""
                enclosure = item.find('enclosure')
                if enclosure and enclosure.get('url'):
                    image_url = enclosure.get('url')
                else:
                    # Look for media:content
                    media_content = item.find('media:content') or item.find('content')
                    if media_content and media_content.get('url'):
                        image_url = media_content.get('url')
                    else:
                        # Extract image from description HTML
                        if desc_text:
                            img_soup = BeautifulSoup(desc_text, 'html.parser')
                            img = img_soup.find('img')
                            if img and img.get('src'):
                                image_url = img.get('src')
                                
                if not image_url and link_text:
                    try:
                        page_res = requests.get(link_text, headers=headers, timeout=5)
                        if page_res.status_code == 200:
                            page_soup = BeautifulSoup(page_res.content, 'html.parser')
                            og_img = page_soup.find('meta', property='og:image') or page_soup.find('meta', attrs={'name': 'twitter:image'})
                            if og_img and og_img.get('content'):
                                image_url = og_img.get('content')
                    except Exception as pe:
                        logger.warning(f"Failed to scrape og:image from {link_text}: {pe}")
                                
                items.append({
                    'title': title_text,
                    'link': link_text,
                    'description': BeautifulSoup(desc_text, 'html.parser').get_text(),
                    'image_url': image_url,
                    'guid': guid_text
                })
        else:
            # Standard Webpage format (fallback HTML parsing)
            html_soup = BeautifulSoup(content, 'html.parser')
            # Look for article links or common news containers
            articles = html_soup.find_all('article') or html_soup.find_all('div', class_=re.compile(r'post|article|news-item'))
            for idx, art in enumerate(articles[:10]):
                link_tag = art.find('a', href=True)
                title_tag = art.find(['h1', 'h2', 'h3', 'h4']) or art.find(class_=re.compile(r'title'))
                img_tag = art.find('img')
                
                if link_tag and title_tag:
                    title_text = title_tag.get_text().strip()
                    link_text = link_tag['href']
                    if not link_text.startswith('http'):
                        # Resolve relative links
                        from urllib.parse import urljoin
                        link_text = urljoin(source_url, link_text)
                    
                    image_url = img_tag.get('src') if img_tag else ""
                    if image_url and not image_url.startswith('http'):
                        from urllib.parse import urljoin
                        image_url = urljoin(source_url, image_url)
                        
                    items.append({
                        'title': title_text,
                        'link': link_text,
                        'description': title_text,
                        'image_url': image_url,
                        'guid': link_text
                    })
    except Exception as e:
        logger.error(f"Error fetching news from source {source_url}: {e}")
        
    return items


def fetch_image_file(image_url):
    """
    Downloads an image from a URL and returns a Django ContentFile, or None.
    """
    if not image_url:
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        res = requests.get(image_url, headers=headers, timeout=10)
        res.raise_for_status()
        
        # Get filename
        filename = image_url.split('/')[-1]
        if '?' in filename:
            filename = filename.split('?')[0]
        if not filename or '.' not in filename:
            filename = 'cover.jpg'
            
        try:
            from PIL import Image
            import io
            
            img = Image.open(io.BytesIO(res.content))
            width, height = img.size
            # Crop bottom 10%
            cropped_img = img.crop((0, 0, width, int(height * 0.90)))
            
            img_io = io.BytesIO()
            fmt = img.format if img.format else 'JPEG'
            cropped_img.save(img_io, format=fmt, quality=90)
            img_io.seek(0)
            
            return ContentFile(img_io.read(), name=filename)
        except Exception as pe:
            logger.warning(f"Failed to crop image watermark: {pe}")
            return ContentFile(res.content, name=filename)
            
    except Exception as e:
        logger.error(f"Error downloading image {image_url}: {e}")
    return None


def generate_slug_for_title(title):
    """
    Generates a unique, clean slug for an article title.
    """
    from django.utils.text import slugify
    import uuid
    # Standard slugify handles ASCII, but allow unicode for Arabic
    slug = re.sub(r'[^\w\s-]', '', title).strip().lower()
    slug = re.sub(r'[-\s]+', '-', slug)
    # Check uniqueness
    if not slug:
        slug = f"article-{uuid.uuid4().hex[:6]}"
    
    orig_slug = slug
    counter = 1
    while Article.all_objects.filter(slug=slug).exists():
        slug = f"{orig_slug}-{counter}"
        counter += 1
    return slug


def get_or_create_ai_author():
    """
    Gets or creates a default system author for AI-generated articles.
    """
    user, created = User.objects.get_or_create(
        username='ai_writer',
        defaults={
            'first_name': 'الذكاء',
            'last_name': 'الاصطناعي',
            'email': 'ai@almaghrib.com',
            'is_staff': True,
            'is_active': True
        }
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


def push_article_to_wordpress(wp_site, article):
    """
    Publishes an article to an external WordPress site via REST API.
    Handles uploading the cover image first and mapping categories.
    """
    from requests.auth import HTTPBasicAuth
    
    base_url = wp_site.url.rstrip('/')
    media_url = f"{base_url}/wp-json/wp/v2/media"
    posts_url = f"{base_url}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(wp_site.username, wp_site.application_password)
    
    featured_media_id = None
    
    # 1. Upload cover image first if it exists
    if article.cover_image:
        try:
            image_name = article.cover_image.name.split('/')[-1]
            content_type = 'image/jpeg'
            if image_name.endswith('.webp'):
                content_type = 'image/webp'
            elif image_name.endswith('.png'):
                content_type = 'image/png'
                
            headers = {
                'Content-Disposition': f'attachment; filename={image_name}',
                'Content-Type': content_type
            }
            
            # Read binary data
            with article.cover_image.open('rb') as img_file:
                img_data = img_file.read()
                
            response = requests.post(media_url, auth=auth, headers=headers, data=img_data, timeout=20)
            
            if response.status_code == 201:
                media_data = response.json()
                featured_media_id = media_data.get('id')
                logger.info(f"Successfully uploaded media to WP site {wp_site.name}, ID: {featured_media_id}")
            else:
                logger.error(f"Failed to upload media to WP site {wp_site.name}: {response.text}")
        except Exception as e:
            logger.error(f"Error uploading media to WP: {e}")

    # 2. Map categories
    wp_categories = []
    cat_mappings = wp_site.get_category_mappings()
    local_cat_name = article.category.name if article.category else ""
    
    if local_cat_name in cat_mappings:
        try:
            wp_categories.append(int(cat_mappings[local_cat_name]))
        except ValueError:
            pass
            
    # 3. Prepare post body
    payload = {
        'title': article.title,
        'content': article.body,
        'excerpt': article.excerpt or '',
        'status': 'publish',
    }
    if featured_media_id:
        payload['featured_media'] = featured_media_id
    if wp_categories:
        payload['categories'] = wp_categories
        
    # 4. Push post
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(posts_url, auth=auth, headers=headers, json=payload, timeout=20)
        if response.status_code == 201:
            post_data = response.json()
            published_url = post_data.get('link', '')
            logger.info(f"Successfully syndicated article to WordPress site {wp_site.name}, URL: {published_url}")
            return published_url
        else:
            logger.error(f"Failed to push post to WP site {wp_site.name}: {response.text}")
    except Exception as e:
        logger.error(f"Error pushing post to WP: {e}")
        
    return None


def run_ai_generation_cycle():
    """
    Executes a complete AI generation cycle:
    1. Reads active settings.
    2. Identifies news categories that need updates.
    3. Fetches the source news items.
    4. Filters out duplicate news items.
    5. Calls Gemini API to rewrite articles.
    6. Downloads cover images.
    7. Saves the synthesized articles.
    """
    ai_settings = AISettings.get_settings()
    if not ai_settings.is_active:
        logger.info("AI Generation system is inactive.")
        return 0
        
    api_key = ai_settings.gemini_api_key or getattr(settings, 'GEMINI_API_KEY', None)
    if not api_key:
        logger.error("Gemini API key is not configured. Aborting run.")
        return 0

    # Get active news sources (filtered by local_sources if configured)
    local_sources_qs = ai_settings.local_sources.filter(is_active=True)
    sources = local_sources_qs if local_sources_qs.exists() else AISource.objects.filter(is_active=True)
    if not sources.exists():
        logger.warning("No active AI sources configured.")
        return 0

    # Get allowed categories for classification
    allowed_cats = list(ai_settings.categories.filter(is_active=True))
    if not allowed_cats:
        allowed_cats = list(Category.objects.filter(is_active=True))
        
    categories_list_str = "\n".join([f"- {c.id}: {c.name}" for c in allowed_cats])
    
    limit = ai_settings.articles_per_day
    generated_count = 0
    
    # Loop over all active sources
    for source in sources:
        if generated_count >= limit:
            break
            
        items = fetch_news_items_from_source(source.url)
        if not items:
            continue
            
        # Get WordPress sites mapped to this source
        wp_sites = list(WordPressSite.objects.filter(is_active=True, sources=source))
        
        for item in items:
            if generated_count >= limit:
                break
                
            # Check duplicate
            if AIImportLog.objects.filter(source_url=item['link'], status='success').exists():
                continue
            if Article.all_objects.filter(slug=generate_slug_for_title(item['title'])).exists():
                continue
                
            # Always generate and publish locally first (Case 1)
            prompt = (
                f"بصفتك محررًا صحفيًا محترفًا باللغة العربية، يرجى كتابة خبر صحفي جديد ومصاغ بأسلوبك الخاص بالكامل "
                f"استناداً إلى المعلومات والخبر التالي:\n"
                f"المصدر: {source.name}\n"
                f"عنوان الخبر الأصلي: {item['title']}\n"
                f"تفاصيل الخبر: {item['description']}\n\n"
                f"الرجاء الالتزام التام بالتعليمات التالية:\n"
                f"1. اكتب الخبر باللغة العربية الفصحى وبأسلوب صحفي متميز وجذاب ومحايد.\n"
                f"2. يجب أن لا يزيد حجم الخبر الإجمالي عن {ai_settings.max_words} كلمة إطلاقاً (تأكد أن يتراوح طول الخبر بين 300 إلى 450 كلمة كحد أقصى لتفادي الإطالة).\n"
                f"3. قم بصياغة عنوان مميز وجذاب ومختلف عن العنوان الأصلي.\n"
                f"4. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
                f"5. قم بإرجاع الإجابة بتنسيق JSON حصريًا دون أي علامات markdown أو علامات برمجية إضافية مثل ```json. "
                f"يجب أن يكون ملف الـ JSON يحتوي على المفاتيح التالية تماماً باللغة الإنجليزية:\n"
                f"- \"title\": عنوان الخبر الجديد\n"
                f"- \"excerpt\": ملخص الخبر\n"
                f"- \"body\": محتوى الخبر الكامل بالتنسيق الصحفي مقسماً إلى فقرات باستخدام وسوم HTML للفقرات <p>...</p> حصراً.\n"
                f"- \"category_id\": الرقم التعريفي (ID) للقسم المختار من القائمة المتاحة أدناه.\n\n"
                f"6. اختر القسم الأنسب لموضوع الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}"
            )
            
            ai_response = call_gemini_api(prompt, api_key=api_key)
            if not ai_response:
                AIImportLog.objects.create(
                    source=source,
                    source_url=item['link'],
                    title=item['title'],
                    status='failed',
                    error_message="لم يستجب الـ API الخاص بـ Gemini أو فشل استخراج النص."
                )
                continue
                
            try:
                cleaned_response = ai_response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                cleaned_response = cleaned_response.strip()
                
                data = json.loads(cleaned_response)
                new_title = data.get("title", "").strip()
                new_excerpt = data.get("excerpt", "").strip()
                new_body = data.get("body", "").strip()
                try:
                    chosen_cat_id = int(data.get("category_id"))
                except (ValueError, TypeError):
                    chosen_cat_id = None
                    
                if not new_title or not new_body:
                    raise ValueError("بيانات العنوان أو المحتوى فارغة في استجابة الذكاء الاصطناعي.")
                    
                category = None
                if chosen_cat_id:
                    category = Category.objects.filter(id=chosen_cat_id, is_active=True).first()
                if not category and allowed_cats:
                    category = allowed_cats[0]
                    
                from core.utils import translate_text
                title_en = translate_text(new_title)
                body_en = translate_text(new_body)
                excerpt_en = translate_text(new_excerpt)
                
                author = ai_settings.default_author or get_or_create_ai_author()
                article = Article(
                    title=new_title,
                    title_ar=new_title,
                    title_en=title_en,
                    slug=generate_slug_for_title(new_title),
                    body=new_body,
                    body_ar=new_body,
                    body_en=body_en,
                    excerpt=new_excerpt,
                    excerpt_ar=new_excerpt,
                    excerpt_en=excerpt_en,
                    author=author,
                    category=category,
                    status='published',
                    published_at=timezone.now(),
                    is_featured=False,
                    is_breaking=False,
                    auto_translate=False
                )
                if item.get('image_url'):
                    img_file = fetch_image_file(item['image_url'])
                    if img_file:
                        article.cover_image = img_file
                        
                article.save()
                
                AIImportLog.objects.create(
                    source=source,
                    article=article,
                    wp_site=None,
                    source_url=item['link'],
                    published_url=article.get_absolute_url() if article else '',
                    title=new_title,
                    status='success'
                )
                
                generated_count += 1
            except Exception as ex:
                logger.error(f"Failed to parse/save local article: {ex}")
                AIImportLog.objects.create(
                    source=source,
                    source_url=item['link'],
                    title=item['title'],
                    status='failed',
                    error_message=f"فشل معالجة استجابة الـ JSON: {str(ex)}"
                )
            
            # Case 2: External WordPress sites connected!
            # Generate a unique article for each site
            if wp_sites:
                for wp_site in wp_sites:
                    if generated_count >= limit:
                        break
                        
                    prompt = (
                        f"بصفتك محررًا صحفيًا محترفًا باللغة العربية، يرجى كتابة خبر صحفي جديد ومصاغ بأسلوبك الخاص بالكامل "
                        f"استناداً إلى المعلومات والخبر التالي:\n"
                        f"المصدر: {source.name}\n"
                        f"عنوان الخبر الأصلي: {item['title']}\n"
                        f"تفاصيل الخبر: {item['description']}\n\n"
                        f"الرجاء الالتزام التام بالتعليمات التالية:\n"
                        f"1. اكتب الخبر باللغة العربية الفصحى وبأسلوب صحفي متميز وجذاب ومحايد.\n"
                        f"2. يجب أن لا يزيد حجم الخبر الإجمالي عن {ai_settings.max_words} كلمة إطلاقاً (تأكد أن يتراوح طول الخبر بين 300 إلى 450 كلمة كحد أقصى لتفادي الإطالة).\n"
                        f"3. قم بصياغة عنوان مميز وجذاب ومختلف عن العنوان الأصلي.\n"
                        f"4. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
                        f"5. قم بإرجاع الإجابة بتنسيق JSON حصريًا دون أي علامات markdown أو علامات برمجية إضافية مثل ```json. "
                        f"يجب أن يكون ملف الـ JSON يحتوي على المفاتيح التالية تماماً باللغة الإنجليزية:\n"
                        f"- \"title\": عنوان الخبر الجديد\n"
                        f"- \"excerpt\": ملخص الخبر\n"
                        f"- \"body\": محتوى الخبر الكامل بالتنسيق الصحفي مقسماً إلى فقرات باستخدام وسوم HTML للفقرات <p>...</p> حصراً.\n"
                        f"- \"category_id\": الرقم التعريفي (ID) للقسم المختار من القائمة المتاحة أدناه.\n\n"
                        f"6. اختر القسم الأنسب لموضوع الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}\n\n"
                        f"هام جداً: صغ هذا الخبر بصياغة فريدة ومختلفة تماماً عن أي صياغات سابقة، باستخدام هيكل ومترادفات مختلفة لموقع الويب المحدد: {wp_site.name}."
                    )
                    
                    ai_response = call_gemini_api(prompt, api_key=api_key)
                    if not ai_response:
                        continue
                        
                    try:
                        cleaned_response = ai_response.strip()
                        if cleaned_response.startswith("```json"):
                            cleaned_response = cleaned_response[7:]
                        if cleaned_response.endswith("```"):
                            cleaned_response = cleaned_response[:-3]
                        cleaned_response = cleaned_response.strip()
                        
                        data = json.loads(cleaned_response)
                        new_title = data.get("title", "").strip()
                        new_excerpt = data.get("excerpt", "").strip()
                        new_body = data.get("body", "").strip()
                        try:
                            chosen_cat_id = int(data.get("category_id"))
                        except (ValueError, TypeError):
                            chosen_cat_id = None
                            
                        if not new_title or not new_body:
                            raise ValueError("بيانات العنوان أو المحتوى فارغة.")
                            
                        category = None
                        if chosen_cat_id:
                            category = Category.objects.filter(id=chosen_cat_id, is_active=True).first()
                        if not category and allowed_cats:
                            category = allowed_cats[0]
                            
                        from core.utils import translate_text
                        title_en = translate_text(new_title)
                        body_en = translate_text(new_body)
                        excerpt_en = translate_text(new_excerpt)
                        
                        author = ai_settings.default_author or get_or_create_ai_author()
                        article = Article(
                            title=new_title,
                            title_ar=new_title,
                            title_en=title_en,
                            slug=generate_slug_for_title(new_title),
                            body=new_body,
                            body_ar=new_body,
                            body_en=body_en,
                            excerpt=new_excerpt,
                            excerpt_ar=new_excerpt,
                            excerpt_en=excerpt_en,
                            author=author,
                            category=category,
                            status='draft',
                            published_at=timezone.now(),
                            is_featured=False,
                            is_breaking=False,
                            auto_translate=False
                        )
                        if item.get('image_url'):
                            img_file = fetch_image_file(item['image_url'])
                            if img_file:
                                article.cover_image = img_file
                                
                        article.save()
                        
                        # Push this unique version to this specific WP site
                        published_url = None
                        try:
                            published_url = push_article_to_wordpress(wp_site, article)
                        except Exception as wpe:
                            logger.error(f"Error syndicating to WP site {wp_site.name}: {wpe}")
                            
                        AIImportLog.objects.create(
                            source=source,
                            article=article,
                            wp_site=wp_site,
                            source_url=item['link'],
                            published_url=published_url or '',
                            title=new_title,
                            status='success' if published_url else 'failed',
                            error_message='' if published_url else 'فشل النشر على ووردبريس'
                        )
                        
                        generated_count += 1
                    except Exception as ex:
                        logger.error(f"Failed to generate unique WP article: {ex}")
                        AIImportLog.objects.create(
                            source=source,
                            source_url=item['link'],
                            title=item['title'],
                            status='failed',
                            error_message=f"فشل صياغة فريدة للووردبريس {wp_site.name}: {str(ex)}"
                        )

    # Update last run timestamp
    ai_settings.last_run = timezone.now()
    ai_settings.save()
    
    return generated_count
