import re
import json
import logging
import bleach
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from django.utils import timezone
from django.core.files.base import ContentFile
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.conf import settings
from .models import Article, Category, AISettings, AISource, AIImportLog, WordPressSite

logger = logging.getLogger(__name__)

# Article body is rendered with the `|safe` template filter, so AI output must be
# restricted to a small safe subset before it's ever saved.
ALLOWED_BODY_TAGS = ['p', 'br', 'strong', 'em', 'b', 'i']
# First subheading is h2, then each subsequent one steps down a level (h3, h4, ...).
HEADING_TAGS = ['h2', 'h3', 'h4', 'h5', 'h6']

HEADING_STRUCTURE_INSTRUCTION = (
    "فقرة تمهيدية واحدة بوسم <p>، ثم عناوين فرعية متتالية بحيث يكون أول عنوان فرعي بوسم <h2>، "
    "والعنوان الفرعي الذي يليه بوسم <h3>، والذي يليه بوسم <h4>، وهكذا بحيث ينزل مستوى العنوان درجة "
    "واحدة مع كل عنوان فرعي جديد (لا تستخدم نفس مستوى العنوان مرتين). كل فقرة نصية توضع داخل وسم "
    "<p> تحت عنوانها الفرعي المناسب. لا تستخدم أي وسوم أو خصائص (attributes) أخرى غير <p> والعناوين "
    "الفرعية المذكورة."
)

# Shared writing-style instruction added to every generation prompt, aimed at
# Yoast's readability checks (short sentences/paragraphs, varied sentence
# openings, transition words, active voice) - all structural checks that
# apply regardless of Yoast's language support level for Arabic.
READABILITY_INSTRUCTION = (
    "اكتب بأسلوب سهل القراءة ومتوافق مع تحليل يوست (Yoast Readability): استخدم جملاً قصيرة "
    "(لا تتجاوز 20 كلمة للجملة الواحدة)، وفقرات قصيرة (2-3 جمل كحد أقصى لكل فقرة)، ونوّع بداية "
    "الجمل المتتالية ولا تبدأ جملتين متتاليتين بنفس الكلمة، واستخدم كلمات ربط انتقالية بين الجمل "
    "(مثل: بالإضافة إلى ذلك، ومع ذلك، على سبيل المثال، في المقابل، وبالتالي) حيثما كان ذلك طبيعياً، "
    "وفضّل صيغة المبني للمعلوم على المبني للمجهول."
)


def sanitize_ai_body(html, allow_headings=False, allow_links=False, link_base_url=None):
    """
    Strips any tag/attribute outside a safe allowlist from AI-generated article HTML.
    When allow_links is set, <a href> is kept only if its host matches link_base_url -
    the AI is never trusted to place a link to an arbitrary/external domain.
    """
    tags = list(ALLOWED_BODY_TAGS)
    attributes = {}
    if allow_headings:
        tags += HEADING_TAGS
    if allow_links:
        tags += ['a']
        attributes['a'] = ['href']

    cleaned = bleach.clean(html or '', tags=tags, attributes=attributes, protocols=['http', 'https'], strip=True)

    if allow_links and link_base_url:
        allowed_host = urlparse(link_base_url).netloc
        soup = BeautifulSoup(cleaned, 'html.parser')
        for a_tag in soup.find_all('a'):
            href = a_tag.get('href', '')
            if urlparse(href).netloc != allowed_host:
                a_tag.unwrap()
        cleaned = str(soup)

    return cleaned


def sanitize_ai_text(text):
    """Strips all HTML from AI-generated plain-text fields (title, excerpt)."""
    return bleach.clean(text or '', tags=[], attributes={}, strip=True)


def apply_heading_color(html, color):
    """
    Applies the WordPress site's configured heading_color to every subheading tag.
    Done server-side (never trusts a color/style coming from the AI response).
    """
    if not html or not color or not re.match(r'^#[0-9A-Fa-f]{6}$', color):
        return html
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(HEADING_TAGS):
        tag['style'] = f'color: {color};'
    return str(soup)

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
        
        # Try parsing as RSS/XML with fallback
        try:
            soup = BeautifulSoup(content, 'lxml-xml')
        except Exception:
            try:
                soup = BeautifulSoup(content, 'xml')
            except Exception:
                soup = BeautifulSoup(content, 'html.parser')
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


def fetch_recent_wp_posts(wp_site, limit=5):
    """
    Fetches a small list of recently published posts from the target WordPress
    site's own public REST API, to offer as internal-link candidates. Read-only
    and unauthenticated - these are just the site's normal public posts.
    """
    base_url = wp_site.url.rstrip('/')
    try:
        resp = requests.get(
            f"{base_url}/wp-json/wp/v2/posts",
            params={'per_page': limit, '_fields': 'title,link'},
            timeout=10
        )
        resp.raise_for_status()
        posts = []
        for p in resp.json():
            link = p.get('link', '')
            title = p.get('title', {}).get('rendered', '')
            if link and title:
                posts.append({'title': title, 'link': link})
        return posts
    except Exception as e:
        logger.warning(f"Failed to fetch recent posts from {wp_site.name} for internal linking: {e}")
        return []


GOLD_SPOT_API_URL = 'https://api.gold-api.com/price/XAU'
GOLD_FX_API_URL = 'https://open.er-api.com/v6/latest/USD'
GRAMS_PER_TROY_OUNCE = 31.1034768


def fetch_live_gold_prices():
    """
    Fetches the live gold spot price (USD/troy ounce, gold-api.com) and the
    USD->EGP exchange rate (open.er-api.com) - both free, keyless, public
    APIs - and computes per-gram Egyptian prices for common karats.
    Returns None if either request fails.
    """
    try:
        gold_resp = requests.get(GOLD_SPOT_API_URL, timeout=10)
        gold_resp.raise_for_status()
        spot_usd_per_oz = float(gold_resp.json()['price'])

        fx_resp = requests.get(GOLD_FX_API_URL, timeout=10)
        fx_resp.raise_for_status()
        usd_to_egp = float(fx_resp.json()['rates']['EGP'])
    except Exception as e:
        logger.error(f"Failed to fetch live gold price data: {e}")
        return None

    price_24k_egp = (spot_usd_per_oz / GRAMS_PER_TROY_OUNCE) * usd_to_egp
    price_21k_egp = price_24k_egp * 0.875
    return {
        'spot_usd_per_oz': round(spot_usd_per_oz, 2),
        'usd_to_egp': round(usd_to_egp, 2),
        'price_24k_egp': round(price_24k_egp, 2),
        'price_22k_egp': round(price_24k_egp * 0.916, 2),
        'price_21k_egp': round(price_21k_egp, 2),
        'price_18k_egp': round(price_24k_egp * 0.75, 2),
        'price_14k_egp': round(price_24k_egp * 0.585, 2),
        # The Egyptian gold pound (جنيه الذهب) is traditionally minted at 21k, ~8 grams.
        'gold_pound_egp': round(price_21k_egp * 8, 2),
        'timestamp': timezone.now(),
    }


def get_or_create_wp_tag_ids(wp_site, tag_names, auth):
    """
    Looks up each tag name via the WordPress REST API and creates it if missing.
    Returns the list of resolved WordPress tag IDs.
    """
    base_url = wp_site.url.rstrip('/')
    tags_url = f"{base_url}/wp-json/wp/v2/tags"
    tag_ids = []
    seen = set()
    for name in tag_names:
        name = (name or '').strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            resp = requests.get(tags_url, auth=auth, params={'search': name}, timeout=10)
            resp.raise_for_status()
            match = next((t for t in resp.json() if t.get('name', '').strip().lower() == name.lower()), None)
            if match:
                tag_ids.append(match['id'])
                continue
            create_resp = requests.post(tags_url, auth=auth, json={'name': name}, timeout=10)
            if create_resp.status_code in (200, 201):
                tag_ids.append(create_resp.json()['id'])
            else:
                logger.warning(f"Failed to create WP tag '{name}' on {wp_site.name}: {create_resp.text}")
        except Exception as e:
            logger.warning(f"Failed to get/create WP tag '{name}' on {wp_site.name}: {e}")
    return tag_ids


def push_article_to_wordpress(wp_site, article, extra_tag_names=None, focus_keyword=None, meta_description=None):
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
    if wp_site.wp_author_id:
        payload['author'] = wp_site.wp_author_id
    if featured_media_id:
        payload['featured_media'] = featured_media_id
    if wp_categories:
        payload['categories'] = wp_categories
    if extra_tag_names:
        tag_ids = get_or_create_wp_tag_ids(wp_site, extra_tag_names, auth)
        if tag_ids:
            payload['tags'] = tag_ids
    if focus_keyword or meta_description:
        payload['meta'] = {}
        if focus_keyword:
            payload['meta']['_yoast_wpseo_focuskw'] = focus_keyword
        if meta_description:
            payload['meta']['_yoast_wpseo_metadesc'] = meta_description

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


def generate_gold_price_article_for_site(wp_site, gold_data, comparison_text, ai_settings, api_key, allowed_cats, categories_list_str):
    """
    Writes and publishes a fresh gold-price article to a single WordPress site,
    using the exact real numbers in gold_data rather than any AI-invented figures.
    Returns True on a successful publish, False otherwise.
    """
    if wp_site.use_rich_formatting:
        body_format_instruction = f"محتوى الخبر الكامل مقسماً بأسلوب متوافق مع السيو (SEO): {HEADING_STRUCTURE_INSTRUCTION}"
    else:
        body_format_instruction = "محتوى الخبر الكامل بالتنسيق الصحفي مقسماً إلى فقرات باستخدام وسوم HTML للفقرات <p>...</p> حصراً."

    internal_link_instruction = ""
    if wp_site.use_internal_links:
        candidate_posts = fetch_recent_wp_posts(wp_site)
        if candidate_posts:
            links_list_str = "\n".join([f"- {p['title']}: {p['link']}" for p in candidate_posts])
            internal_link_instruction = (
                f"\nإن أمكن بشكل طبيعي، ضمّن رابطاً داخلياً واحداً أو رابطين على الأكثر باستخدام وسم "
                f"<a href=\"...\">نص الرابط</a> داخل فقرات الخبر، يشيران فقط إلى أحد الروابط التالية "
                f"لمقالات أخرى على نفس الموقع (لا تخترع أي رابط جديد، استخدم الروابط أدناه حرفياً):\n{links_list_str}"
            )

    comparison_line = f"\n{comparison_text}" if comparison_text else "\nلا تتوفر بيانات مقارنة بتحديث سابق - لا تذكر أي مقارنة أو نسبة تغيير في هذه الحالة."

    prompt = (
        f"بصفتك محررًا اقتصاديًا محترفًا باللغة العربية، اكتب خبرًا صحفيًا محدَّثًا عن سعر الذهب اليوم في مصر، "
        f"معتمداً حصرياً على الأرقام الحقيقية التالية المأخوذة من السوق العالمية لحظة كتابة الخبر - "
        f"اذكرها كما هي تماماً دون تقريب أو اختراع أي رقم بديل:\n"
        f"- سعر أوقية الذهب عالمياً: {gold_data['spot_usd_per_oz']} دولار أمريكي\n"
        f"- سعر صرف الدولار: {gold_data['usd_to_egp']} جنيه مصري\n"
        f"- سعر جرام الذهب عيار 24: {gold_data['price_24k_egp']} جنيه مصري\n"
        f"- سعر جرام الذهب عيار 22: {gold_data['price_22k_egp']} جنيه مصري\n"
        f"- سعر جرام الذهب عيار 21: {gold_data['price_21k_egp']} جنيه مصري\n"
        f"- سعر جرام الذهب عيار 18: {gold_data['price_18k_egp']} جنيه مصري\n"
        f"- سعر جرام الذهب عيار 14: {gold_data['price_14k_egp']} جنيه مصري\n"
        f"- سعر جنيه الذهب (8 جرام عيار 21): {gold_data['gold_pound_egp']} جنيه مصري"
        f"{comparison_line}\n\n"
        f"الرجاء الالتزام التام بالتعليمات التالية:\n"
        f"1. اكتب بأسلوب صحفي اقتصادي مباشر وواضح، بين 250 و400 كلمة. {READABILITY_INSTRUCTION}\n"
        f"2. قم بصياغة عنوان جذاب يذكر تحديث سعر الذهب اليوم.\n"
        f"3. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
        f"4. أضف في نهاية الخبر فقرة قصيرة بعنوان \"نظرة عامة على السوق\" تصف الاتجاه العام لحركة الذهب عالمياً "
        f"بصياغة عامة ومتحفظة (مثل تأثير سعر الصرف أو حركة السوق العالمي)، على أن تنتهي الفقرة حرفياً بجملة توضيحية "
        f"مشابهة لـ: \"هذه قراءة عامة لحركة السوق ولا تُعد توصية استثمارية.\" لا تذكر أي أرقام أو مستويات أو نسب "
        f"مستقبلية مختلَقة، فقط وصف عام للاتجاه.\n"
        f"5. قم بإرجاع الإجابة بتنسيق JSON حصريًا دون أي علامات markdown أو علامات برمجية إضافية مثل ```json. "
        f"يجب أن يكون ملف الـ JSON يحتوي على المفاتيح التالية تماماً باللغة الإنجليزية:\n"
        f"- \"title\": عنوان الخبر\n"
        f"- \"excerpt\": ملخص الخبر\n"
        f"- \"body\": {body_format_instruction}\n"
        f"- \"category_id\": الرقم التعريفي (ID) للقسم المختار من القائمة المتاحة أدناه.\n"
        f"- \"focus_keyword\": عبارة مفتاحية قصيرة (2-4 كلمات) تلخص موضوع الخبر، لاستخدامها في تحليل السيو (SEO).\n"
        f"- \"meta_description\": وصف تعريفي (Meta Description) لمحركات البحث لا يتجاوز 155 حرفاً.\n"
        f"- \"tags\": قائمة (array) من 3 إلى 5 وسوم؛ يجب أن يكون كل وسم مرتبطاً مباشرة بمحتوى هذا الخبر تحديداً "
        f"(وليس عاماً)، وأن يكون عبارة بحثية واقعية يستخدمها القارئ فعلاً عند البحث في جوجل عن هذا الموضوع بالذات "
        f"(مثال: \"سعر الذهب اليوم\"، \"سعر جرام الذهب عيار 21\"، \"سعر جنيه الذهب في مصر\").\n\n"
        f"6. اختر القسم الأنسب لهذا الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}\n"
        f"{internal_link_instruction}"
    )

    ai_response = call_gemini_api(prompt, api_key=api_key)
    if not ai_response:
        AIImportLog.objects.create(
            source=None,
            source_url=GOLD_SPOT_API_URL,
            wp_site=wp_site,
            title="تحديث سعر الذهب",
            status='failed',
            error_message="لم يستجب الـ API الخاص بـ Gemini أو فشل استخراج النص."
        )
        return False

    try:
        cleaned_response = ai_response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()

        data = json.loads(cleaned_response)
        new_title = sanitize_ai_text(data.get("title", "").strip())
        new_excerpt = sanitize_ai_text(data.get("excerpt", "").strip())
        new_body = sanitize_ai_body(
            data.get("body", "").strip(),
            allow_headings=wp_site.use_rich_formatting,
            allow_links=wp_site.use_internal_links,
            link_base_url=wp_site.url,
        )
        if wp_site.use_rich_formatting:
            new_body = apply_heading_color(new_body, wp_site.heading_color)
        focus_keyword = sanitize_ai_text(data.get("focus_keyword", "").strip())
        meta_description = sanitize_ai_text(data.get("meta_description", "").strip())
        raw_tags = data.get("tags") or []
        if not isinstance(raw_tags, list):
            raw_tags = []
        ai_tags = [sanitize_ai_text(str(t).strip()) for t in raw_tags[:5] if str(t).strip()]

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
        article.save()

        tag_names = (ai_tags if ai_tags else ([category.name] if category else [])) + wp_site.get_site_tags_list()
        published_url = None
        try:
            published_url = push_article_to_wordpress(
                wp_site, article, extra_tag_names=tag_names,
                focus_keyword=focus_keyword, meta_description=meta_description
            )
        except Exception as wpe:
            logger.error(f"Error syndicating gold price article to WP site {wp_site.name}: {wpe}")

        AIImportLog.objects.create(
            source=None,
            article=article,
            wp_site=wp_site,
            source_url=GOLD_SPOT_API_URL,
            published_url=published_url or '',
            title=new_title,
            status='success' if published_url else 'failed',
            error_message='' if published_url else 'فشل النشر على ووردبريس'
        )
        return bool(published_url)
    except Exception as ex:
        logger.error(f"Failed to generate gold price article for {wp_site.name}: {ex}")
        AIImportLog.objects.create(
            source=None,
            source_url=GOLD_SPOT_API_URL,
            wp_site=wp_site,
            title="تحديث سعر الذهب",
            status='failed',
            error_message=f"فشل صياغة خبر سعر الذهب لـ {wp_site.name}: {str(ex)}"
        )
        return False


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

    # Iterate every active source. local_sources (if configured) only restricts which
    # sources are eligible to publish to the main local site (checked per-source below) -
    # it must not hide sources that are only linked to a WordPress site.
    local_sources_qs = ai_settings.local_sources.filter(is_active=True)
    local_sources_restricted = local_sources_qs.exists()
    local_source_ids = set(local_sources_qs.values_list('id', flat=True)) if local_sources_restricted else None
    sources = AISource.objects.filter(is_active=True)
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

    # Track how many articles each WordPress site has already received today,
    # so its per-site daily_limit is honored on top of the global limit.
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    wp_site_counts = {
        row['wp_site']: row['count']
        for row in AIImportLog.objects.filter(
            status='success', wp_site__isnull=False, created_at__gte=today_start
        ).values('wp_site').annotate(count=Count('id'))
    }

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
                
            source_allowed_for_local = not local_sources_restricted or source.id in local_source_ids
            if ai_settings.publish_to_main_site and source_allowed_for_local:
                # Always generate and publish locally first (Case 1)
                prompt = (
                    f"بصفتك محررًا صحفيًا محترفًا باللغة العربية، يرجى كتابة خبر صحفي جديد ومصاغ بأسلوبك الخاص بالكامل "
                    f"استناداً إلى المعلومات والخبر التالي:\n"
                    f"المصدر: {source.name}\n"
                    f"عنوان الخبر الأصلي: {item['title']}\n"
                    f"تفاصيل الخبر: {item['description']}\n\n"
                    f"الرجاء الالتزام التام بالتعليمات التالية:\n"
                    f"1. اكتب الخبر باللغة العربية الفصحى وبأسلوب صحفي متميز وجذاب ومحايد. {READABILITY_INSTRUCTION}\n"
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
                    new_title = sanitize_ai_text(data.get("title", "").strip())
                    new_excerpt = sanitize_ai_text(data.get("excerpt", "").strip())
                    new_body = sanitize_ai_body(data.get("body", "").strip())
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
                    if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                        continue

                    if wp_site.use_rich_formatting:
                        body_format_instruction = f"محتوى الخبر الكامل مقسماً بأسلوب متوافق مع السيو (SEO): {HEADING_STRUCTURE_INSTRUCTION}"
                    else:
                        body_format_instruction = "محتوى الخبر الكامل بالتنسيق الصحفي مقسماً إلى فقرات باستخدام وسوم HTML للفقرات <p>...</p> حصراً."

                    internal_link_instruction = ""
                    if wp_site.use_internal_links:
                        candidate_posts = fetch_recent_wp_posts(wp_site)
                        if candidate_posts:
                            links_list_str = "\n".join([f"- {p['title']}: {p['link']}" for p in candidate_posts])
                            internal_link_instruction = (
                                f"\n7. إن أمكن بشكل طبيعي، ضمّن رابطاً داخلياً واحداً أو رابطين على الأكثر باستخدام وسم "
                                f"<a href=\"...\">نص الرابط</a> داخل فقرات الخبر، يشيران فقط إلى أحد الروابط التالية "
                                f"لمقالات أخرى على نفس الموقع (لا تخترع أي رابط جديد، استخدم الروابط أدناه حرفياً):\n{links_list_str}"
                            )

                    explainer_instruction = ""
                    if wp_site.use_explainer_style:
                        explainer_instruction = (
                            "\n8. إذا كان هذا الخبر يتعلق بقرار تنظيمي أو رسوم أو ضرائب أو تغييرات أسعار تستحق شرحاً "
                            "تفصيلياً (وليس مجرد خبر عاجل سريع)، فاختر أسلوباً تفسيرياً بدلاً من الأسلوب المعتاد: صغ "
                            "العنوان كسؤال يعكس جوهر الموضوع، وقسّم محتوى الخبر إلى عناوين فرعية على شكل أسئلة فرعية "
                            "(مثل: لماذا...؟ هل...؟ ما حجم/تأثير...؟ كيف...؟) باتباع نفس ترتيب مستويات العناوين "
                            "الموضح أعلاه (أول عنوان فرعي <h2>، والذي يليه <h3>، وهكذا)، بحيث يجيب كل قسم عن سؤاله "
                            "مباشرة، ويمكن أن يصل طول الخبر في هذه الحالة حتى 800 كلمة متجاوزاً الحد المذكور في "
                            "التعليمة الثانية. أما إذا كان الخبر عاجلاً أو حدثياً عادياً لا يحتاج شرحاً، فاتبع التنسيق "
                            "المعتاد القصير."
                        )

                    prompt = (
                        f"بصفتك محررًا صحفيًا محترفًا باللغة العربية، يرجى كتابة خبر صحفي جديد ومصاغ بأسلوبك الخاص بالكامل "
                        f"استناداً إلى المعلومات والخبر التالي:\n"
                        f"المصدر: {source.name}\n"
                        f"عنوان الخبر الأصلي: {item['title']}\n"
                        f"تفاصيل الخبر: {item['description']}\n\n"
                        f"الرجاء الالتزام التام بالتعليمات التالية:\n"
                        f"1. اكتب الخبر باللغة العربية الفصحى وبأسلوب صحفي متميز وجذاب ومحايد. {READABILITY_INSTRUCTION}\n"
                        f"2. يجب أن لا يزيد حجم الخبر الإجمالي عن {ai_settings.max_words} كلمة إطلاقاً (تأكد أن يتراوح طول الخبر بين 300 إلى 450 كلمة كحد أقصى لتفادي الإطالة).\n"
                        f"3. قم بصياغة عنوان مميز وجذاب ومختلف عن العنوان الأصلي.\n"
                        f"4. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
                        f"5. قم بإرجاع الإجابة بتنسيق JSON حصريًا دون أي علامات markdown أو علامات برمجية إضافية مثل ```json. "
                        f"يجب أن يكون ملف الـ JSON يحتوي على المفاتيح التالية تماماً باللغة الإنجليزية:\n"
                        f"- \"title\": عنوان الخبر الجديد\n"
                        f"- \"excerpt\": ملخص الخبر\n"
                        f"- \"body\": {body_format_instruction}\n"
                        f"- \"category_id\": الرقم التعريفي (ID) للقسم المختار من القائمة المتاحة أدناه.\n"
                        f"- \"focus_keyword\": عبارة مفتاحية قصيرة (2-4 كلمات) تلخص موضوع الخبر الأساسي، لاستخدامها في تحليل السيو (SEO).\n"
                        f"- \"meta_description\": وصف تعريفي (Meta Description) لمحركات البحث لا يتجاوز 155 حرفاً، يتضمن العبارة المفتاحية أعلاه.\n"
                        f"- \"tags\": قائمة (array) من 3 إلى 5 وسوم؛ يجب أن يكون كل وسم مرتبطاً مباشرة بمحتوى هذا "
                        f"الخبر تحديداً (وليس عاماً)، وأن يكون عبارة بحثية واقعية يستخدمها القارئ فعلاً عند البحث في "
                        f"جوجل عن هذا الموضوع بالذات (مثال لخبر عن سعر اليورو: \"سعر اليورو اليوم\"، \"اليورو مقابل "
                        f"الجنيه\")، بدون ذكر اسم أي موقع إخباري.\n\n"
                        f"6. اختر القسم الأنسب لموضوع الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}\n"
                        f"{internal_link_instruction}"
                        f"{explainer_instruction}\n\n"
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
                        new_title = sanitize_ai_text(data.get("title", "").strip())
                        new_excerpt = sanitize_ai_text(data.get("excerpt", "").strip())
                        new_body = sanitize_ai_body(
                            data.get("body", "").strip(),
                            allow_headings=wp_site.use_rich_formatting or wp_site.use_explainer_style,
                            allow_links=wp_site.use_internal_links,
                            link_base_url=wp_site.url,
                        )
                        if wp_site.use_rich_formatting:
                            new_body = apply_heading_color(new_body, wp_site.heading_color)
                        focus_keyword = sanitize_ai_text(data.get("focus_keyword", "").strip())
                        meta_description = sanitize_ai_text(data.get("meta_description", "").strip())
                        raw_tags = data.get("tags") or []
                        if not isinstance(raw_tags, list):
                            raw_tags = []
                        ai_tags = [sanitize_ai_text(str(t).strip()) for t in raw_tags[:5] if str(t).strip()]
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
                            tag_names = (ai_tags if ai_tags else ([category.name] if category else [])) + wp_site.get_site_tags_list()
                            published_url = push_article_to_wordpress(
                                wp_site, article, extra_tag_names=tag_names,
                                focus_keyword=focus_keyword, meta_description=meta_description
                            )
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
                        if published_url:
                            wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1

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

    # Live gold price articles: independent of RSS sources, generated fresh every
    # cycle run for whichever site(s) opted in, capped by the same daily limits.
    gold_price_sites = WordPressSite.objects.filter(is_active=True, generate_gold_price_articles=True)
    if gold_price_sites.exists():
        gold_data = fetch_live_gold_prices()
        if gold_data:
            comparison_text = ""
            if ai_settings.last_gold_price_24k_egp:
                diff = gold_data['price_24k_egp'] - ai_settings.last_gold_price_24k_egp
                if abs(diff) >= 0.5:
                    direction = "ارتفع" if diff > 0 else "تراجع"
                    comparison_text = (
                        f"- مقارنة حقيقية بآخر تحديث مسجَّل: {direction} سعر جرام الذهب عيار 24 بمقدار "
                        f"{abs(round(diff, 2))} جنيه مصري (اذكر هذه المقارنة بدقة كما هي)."
                    )
            ai_settings.last_gold_price_24k_egp = gold_data['price_24k_egp']
            ai_settings.last_gold_price_at = gold_data['timestamp']
            ai_settings.save(update_fields=['last_gold_price_24k_egp', 'last_gold_price_at'])

            for wp_site in gold_price_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                success = generate_gold_price_article_for_site(
                    wp_site, gold_data, comparison_text, ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
        else:
            logger.error("Failed to fetch live gold price data; skipping gold price article generation this cycle.")

    # Update last run timestamp
    ai_settings.last_run = timezone.now()
    ai_settings.save()
    
    return generated_count
