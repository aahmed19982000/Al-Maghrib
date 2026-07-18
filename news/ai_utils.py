import re
import json
import random
import logging
import bleach
import requests
from datetime import timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from django.utils import timezone
from django.core.files.base import ContentFile
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.conf import settings
from .models import Article, Category, AISettings, AISource, AIImportLog, WordPressSite, WordPressScheduleSlot

logger = logging.getLogger(__name__)

CAIRO_TZ = ZoneInfo("Africa/Cairo")

# Every official/live price topic is excluded from the regular RSS-rewrite
# pipeline - the dedicated generators (generate_gold_price_article_for_site,
# generate_official_commodity_article_for_site, generate_arab_currencies_article_for_site,
# etc.) are the only source of truth for these topics, using real official
# data, to avoid duplicate/conflicting/possibly-fabricated articles.
# Iron/fish use narrower "price of X" phrases rather than the bare word
# ("حديد"/"سمك" alone are too common in unrelated news - e.g. "السكة الحديد"
# railway news - and would wrongly get blocked otherwise).
EXCLUDED_PRICE_TOPIC_KEYWORDS = [
    'ذهب', 'فضة', 'دولار',
    'إسمنت', 'الإسمنت',
    'سعر الحديد', 'أسعار الحديد', 'حديد عز',
    'دواجن',
    'سعر السمك', 'أسعار السمك',
    'أسعار الخضار',
    'الريال السعودي', 'الدينار الكويتي', 'الدرهم الإماراتي',
]


def is_excluded_price_topic(title, description=""):
    """Returns True if the RSS item is about a topic covered by a dedicated live/official price generator."""
    text = f"{title or ''} {description or ''}"
    return any(keyword in text for keyword in EXCLUDED_PRICE_TOPIC_KEYWORDS)


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


def fetch_google_trends_items(source_url):
    """
    Parses Google's daily trending-searches RSS feed. Unlike a normal news
    feed, each <item> is just a trending keyword with an empty description
    and a link back to the trends page itself - the actual real article
    explaining the trend is nested inside <ht:news_item>. This pulls that
    nested article out (the top one per trend) and returns it in the same
    shape as fetch_news_items_from_source.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    items = []
    try:
        response = requests.get(source_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml-xml')

        for trend in soup.find_all('item'):
            trend_title_tag = trend.find('title')
            trend_title = trend_title_tag.text.strip() if trend_title_tag else ""

            news_item = trend.find('ht:news_item')
            if not news_item:
                continue

            title_tag = news_item.find('ht:news_item_title')
            url_tag = news_item.find('ht:news_item_url')
            snippet_tag = news_item.find('ht:news_item_snippet')
            picture_tag = news_item.find('ht:news_item_picture')

            title_text = title_tag.text.strip() if title_tag else trend_title
            link_text = url_tag.text.strip() if url_tag else ""
            snippet_text = snippet_tag.text.strip() if snippet_tag else ""
            image_url = picture_tag.text.strip() if picture_tag else ""

            if not title_text or not link_text:
                continue

            description = f"{snippet_text} (الموضوع الرائج على جوجل: {trend_title})" if snippet_text else f"موضوع رائج على جوجل: {trend_title}"
            items.append({
                'title': title_text,
                'link': link_text,
                'description': description,
                'image_url': image_url,
                'guid': link_text,
            })
    except Exception as e:
        logger.error(f"Error fetching Google Trends items from {source_url}: {e}")
    return items


def fetch_news_items_from_source(source_url):
    """
    Fetches news items from an RSS feed or webpage.
    Returns a list of dictionaries with keys: 'title', 'link', 'description', 'image_url', 'guid'.
    """
    if 'trends.google.com' in source_url:
        return fetch_google_trends_items(source_url)

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


MAX_COVER_IMAGE_SIZE = (900, 600)


def fetch_image_file(image_url):
    """
    Downloads an image from a URL, crops the bottom 10% (source watermarks),
    caps its dimensions to MAX_COVER_IMAGE_SIZE (never upscaled, only shrunk),
    and returns it as a Django ContentFile encoded as JPEG - or None on failure.
    """
    if not image_url:
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        res = requests.get(image_url, headers=headers, timeout=10)
        res.raise_for_status()

        # Get filename, always saved as .jpg since the output is always re-encoded to JPEG below.
        filename = image_url.split('/')[-1]
        if '?' in filename:
            filename = filename.split('?')[0]
        if not filename or '.' not in filename:
            filename = 'cover'
        filename = filename.rsplit('.', 1)[0] + '.jpg'

        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(res.content))
            width, height = img.size
            # Crop bottom 10% (source watermarks) at full resolution first.
            cropped_img = img.crop((0, 0, width, int(height * 0.90)))
            # Cap dimensions to MAX_COVER_IMAGE_SIZE - thumbnail() only ever
            # shrinks, never upscales, so smaller source images are left as-is
            # (upscaling would make them blurrier, not fix quality).
            cropped_img.thumbnail(MAX_COVER_IMAGE_SIZE, Image.LANCZOS)

            # JPEG has no alpha channel - flatten transparency onto white first,
            # otherwise Pillow raises and the except branch below would skip
            # cropping/resizing entirely, silently publishing an oversized image.
            if cropped_img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', cropped_img.size, (255, 255, 255))
                background.paste(cropped_img, mask=cropped_img.convert('RGBA').split()[-1])
                cropped_img = background
            elif cropped_img.mode != 'RGB':
                cropped_img = cropped_img.convert('RGB')

            img_io = io.BytesIO()
            cropped_img.save(img_io, format='JPEG', quality=92, optimize=True)
            img_io.seek(0)

            return ContentFile(img_io.read(), name=filename)
        except Exception as pe:
            logger.warning(f"Failed to process cover image, using original download as-is: {pe}")
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


def pick_default_author(ai_settings):
    """
    Picks one of the configured default authors at random, to vary attributed
    authorship across generated articles. Falls back to the system AI author
    when none are configured.
    """
    authors = list(ai_settings.default_authors.all())
    if authors:
        return random.choice(authors)
    return get_or_create_ai_author()


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


SILVER_SPOT_API_URL = 'https://api.gold-api.com/price/XAG'


def fetch_live_silver_prices():
    """
    Fetches the live silver spot price (USD/troy ounce, gold-api.com) and the
    USD->EGP exchange rate, and computes the per-gram Egyptian price for pure
    (999) silver. Returns None if either request fails.
    """
    try:
        silver_resp = requests.get(SILVER_SPOT_API_URL, timeout=10)
        silver_resp.raise_for_status()
        spot_usd_per_oz = float(silver_resp.json()['price'])

        fx_resp = requests.get(GOLD_FX_API_URL, timeout=10)
        fx_resp.raise_for_status()
        usd_to_egp = float(fx_resp.json()['rates']['EGP'])
    except Exception as e:
        logger.error(f"Failed to fetch live silver price data: {e}")
        return None

    price_999_egp = (spot_usd_per_oz / GRAMS_PER_TROY_OUNCE) * usd_to_egp
    return {
        'spot_usd_per_oz': round(spot_usd_per_oz, 2),
        'usd_to_egp': round(usd_to_egp, 2),
        'price_999_egp': round(price_999_egp, 2),
        'price_925_egp': round(price_999_egp * 0.925, 2),
        'timestamp': timezone.now(),
    }


def fetch_live_dollar_price():
    """
    Fetches the live USD->EGP exchange rate (open.er-api.com, free/keyless).
    Returns None if the request fails.
    """
    try:
        fx_resp = requests.get(GOLD_FX_API_URL, timeout=10)
        fx_resp.raise_for_status()
        usd_to_egp = float(fx_resp.json()['rates']['EGP'])
    except Exception as e:
        logger.error(f"Failed to fetch live dollar price data: {e}")
        return None

    return {
        'usd_to_egp': round(usd_to_egp, 2),
        'timestamp': timezone.now(),
    }


# Official commodity price data from Egypt's Cabinet Information and Decision
# Support Center (IDSC) - the same backend that powers agriprice.gov.eg.
# Free, keyless, and includes a real day-over-day comparison already computed.
IDSC_API_BASE = 'http://app.prices.idsc.gov.eg/api'
IDSC_INDICATOR_IDS = {
    'iron': 7,              # حديد عز
    'iron_investment': 8,   # حديد إستثماري
    'cement': 92,           # الأسمنت الرمادي
    'poultry': 880,         # الدواجن الطازجة
    'fish': 827,            # السمك (المتوسط العام)
    'fish_tilapia': 326,    # البلطي (ممتاز)
    'fish_shrimp': 331,     # الجمبري (وسط)
    'fish_sardine': 338,    # السردين المجمد
    'tomatoes': 2,
    'potatoes': 1,
    'onions': 824,
}


def fetch_idsc_indicator(indicator_key):
    """
    Fetches official real-time retail price data (with built-in comparison to
    yesterday/last week) for a single commodity from the IDSC price API.
    Returns None if the request fails.
    """
    indicator_id = IDSC_INDICATOR_IDS[indicator_key]
    try:
        resp = requests.get(
            f"{IDSC_API_BASE}/PricesData/GetMainIndicatorData/{indicator_id}",
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            'retail_price': data.get('retailAvgPrice'),
            'change_yesterday': data.get('retailComYest'),
            'change_week': data.get('retailComWeek'),
            'date': data.get('insertionDate'),
        }
    except Exception as e:
        logger.error(f"Failed to fetch IDSC indicator '{indicator_key}': {e}")
        return None


# Arab currencies plus the other non-Arab foreign currencies the same IDSC
# endpoint tracks (Euro, British Pound, Swiss Franc) - the US Dollar is
# deliberately excluded here since it already has its own dedicated article.
ARAB_CURRENCY_NAMES = ['ريال سعودي', 'دينار كويتي', 'درهم إماراتي', 'يورو', 'جنيه استرليني', 'فرنك سويسري']


def fetch_arab_currency_rates():
    """
    Fetches official real buy/sell exchange rates (with built-in comparison to
    yesterday) for Arab and other foreign currencies against the Egyptian
    pound, from the same IDSC price API used for gold/commodities. Returns
    None if the request fails or none of the expected currencies are present
    in the response.
    """
    try:
        resp = requests.get(
            f"{IDSC_API_BASE}/PricesData/GetCurrencyExchange",
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10,
        )
        resp.raise_for_status()
        all_rates = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch currency exchange rates: {e}")
        return None

    result = []
    for currency in all_rates:
        if currency.get('name') in ARAB_CURRENCY_NAMES:
            result.append({
                'name': currency['name'],
                'buy_rate': currency.get('buyRate'),
                'sell_rate': currency.get('sellRate'),
                'change_yesterday': currency.get('sellRateDially'),
            })
    return result if result else None


def _is_due(last_run_at, min_hours):
    """True if last_run_at is empty or old enough that min_hours have elapsed since."""
    if not last_run_at:
        return True
    return (timezone.now() - last_run_at) >= timedelta(hours=min_hours)


# Must stay in sync with the Celery Beat interval for scrape_and_generate_news_task
# (every 10 minutes) - wide enough that a slot's window is always caught by at
# least one cycle tick, even if a tick runs a little late.
SLOT_TOLERANCE_MINUTES = 12


def get_due_slot(wp_site, content_type, tolerance_minutes=SLOT_TOLERANCE_MINUTES):
    """
    Returns the active WordPressScheduleSlot on this site that lists
    `content_type` among its content types, whose configured time is within
    `tolerance_minutes` of the current Cairo-local time, and where THIS
    content type specifically hasn't already run today (Cairo date). Tracked
    per-type (not per-slot) so a slot listing several types (e.g. iron +
    cement together) runs each of them independently - one type running
    doesn't block the others in the same slot for the rest of the day.
    Returns None if nothing matches right now.
    """
    now_cairo = timezone.now().astimezone(CAIRO_TZ)
    today_cairo = now_cairo.date().isoformat()
    for slot in wp_site.schedule_slots.filter(is_active=True):
        if content_type not in slot.get_content_types_list():
            continue
        if slot.get_last_run_date_for_type(content_type) == today_cairo:
            continue
        slot_dt = now_cairo.replace(hour=slot.time_of_day.hour, minute=slot.time_of_day.minute, second=0, microsecond=0)
        if abs((now_cairo - slot_dt).total_seconds()) <= tolerance_minutes * 60:
            return slot
    return None


def mark_slot_run(slot, content_type):
    """Marks a specific content type on this slot as having run today (Cairo date)."""
    slot.set_last_run_date_for_type(content_type, timezone.now().astimezone(CAIRO_TZ).date())


def get_regular_news_run_cap(wp_site):
    """
    Returns (cap, due_slot) for how many regular RSS/Trends articles this site
    may receive this cycle:
    - Sites with no schedule slots configured keep the legacy fixed
      `articles_per_run` cap, applied every cycle (unchanged behavior).
    - Sites with schedule slots only get "regular" articles when one of their
      slots is due right now, capped by that slot's own `regular_news_count`.
    """
    if not wp_site.schedule_slots.filter(is_active=True).exists():
        return wp_site.articles_per_run, None
    due_slot = get_due_slot(wp_site, 'regular')
    if due_slot:
        return due_slot.regular_news_count, due_slot
    return 0, None


def sites_due_for_type(content_type, legacy_bool_field, ai_settings=None, last_at_field=None, min_hours=20):
    """
    Returns (list_of_wp_sites, due_slots_dict, legacy_used) of which active
    WordPress sites should generate a `content_type` price article this cycle:
    - Sites with schedule slots configured: only included if one of their
      slots lists this content type and is due right now (Cairo time). The
      slot's own per-site `last_run_date` is the sole gate; the legacy global
      once-daily gate below does not apply to these sites.
    - Sites without any schedule slots: fall back to the legacy behavior -
      included if their `legacy_bool_field` toggle is on, gated by the shared
      global `_is_due(ai_settings.<last_at_field>, min_hours)` check (same as
      before this feature existed). Pass `last_at_field=None` for content
      types (like gold) that have always fired every cycle with no gate.
    `legacy_used` is True if at least one non-slot site was included via the
    legacy gate - callers should only bump the shared `ai_settings.<last_at_field>`
    timestamp in that case, so a slot-only fetch doesn't skew the legacy gate
    for sites that aren't using slots.
    """
    result = []
    due_slots = {}
    legacy_used = False
    legacy_gate_open = True
    if last_at_field is not None and ai_settings is not None:
        legacy_gate_open = _is_due(getattr(ai_settings, last_at_field), min_hours)

    for wp_site in WordPressSite.objects.filter(is_active=True):
        has_slots = wp_site.schedule_slots.filter(is_active=True).exists()
        if has_slots:
            slot = get_due_slot(wp_site, content_type)
            if slot:
                result.append(wp_site)
                due_slots[wp_site.id] = slot
        elif getattr(wp_site, legacy_bool_field) and legacy_gate_open:
            result.append(wp_site)
            legacy_used = True

    return result, due_slots, legacy_used


def generate_official_commodity_article_for_site(wp_site, topic_title, items, source_url, ai_settings, api_key, allowed_cats, categories_list_str):
    """
    Writes and publishes a fresh price-update article to a single WordPress site
    using one or more official IDSC price items, e.g. a single commodity (iron,
    cement, poultry, fish) or a small basket (vegetables). `items` is a list of
    (arabic_label, idsc_data_dict) tuples. Numbers come straight from the
    official source, including its own day-over-day comparison - nothing here
    is computed or invented by the AI.
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

    numbers_lines = []
    for label, data in items:
        line = f"- {label}: {data['retail_price']} جنيه"
        if data.get('change_yesterday'):
            direction = "ارتفاع" if data['change_yesterday'] > 0 else "انخفاض"
            line += f" (بـ{direction} {abs(round(data['change_yesterday'], 2))} جنيه مقارنة بالأمس)"
        numbers_lines.append(line)
    numbers_block = "\n".join(numbers_lines)

    prompt = (
        f"بصفتك محررًا اقتصاديًا محترفًا باللغة العربية، اكتب خبرًا صحفيًا محدَّثًا عن {topic_title} في مصر، "
        f"معتمداً حصرياً على الأرقام الرسمية التالية الصادرة عن مركز معلومات مجلس الوزراء المصري لحظة كتابة "
        f"الخبر - اذكرها كما هي تماماً دون تقريب أو اختراع أي رقم بديل:\n"
        f"{numbers_block}\n\n"
        f"الرجاء الالتزام التام بالتعليمات التالية:\n"
        f"1. اكتب بأسلوب صحفي اقتصادي مباشر وواضح، بين 200 و350 كلمة. {READABILITY_INSTRUCTION}\n"
        f"2. قم بصياغة عنوان جذاب يذكر تحديث {topic_title} اليوم.\n"
        f"3. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
        f"4. اذكر المقارنة بالأمس فقط إن وردت في الأرقام أعلاه، ولا تخترع أي مقارنة أو نسبة غير مذكورة.\n"
        f"5. قم بإرجاع الإجابة بتنسيق JSON حصريًا دون أي علامات markdown أو علامات برمجية إضافية مثل ```json. "
        f"يجب أن يكون ملف الـ JSON يحتوي على المفاتيح التالية تماماً باللغة الإنجليزية:\n"
        f"- \"title\": عنوان الخبر\n"
        f"- \"excerpt\": ملخص الخبر\n"
        f"- \"body\": {body_format_instruction}\n"
        f"- \"category_id\": الرقم التعريفي (ID) للقسم المختار من القائمة المتاحة أدناه.\n"
        f"- \"focus_keyword\": عبارة مفتاحية قصيرة (2-4 كلمات) تلخص موضوع الخبر، لاستخدامها في تحليل السيو (SEO).\n"
        f"- \"meta_description\": وصف تعريفي (Meta Description) لمحركات البحث لا يتجاوز 155 حرفاً.\n"
        f"- \"tags\": قائمة (array) من 3 إلى 5 وسوم؛ يجب أن يكون كل وسم مرتبطاً مباشرة بمحتوى هذا الخبر تحديداً "
        f"(وليس عاماً)، وأن يكون عبارة بحثية واقعية يستخدمها القارئ فعلاً عند البحث في جوجل عن هذا الموضوع بالذات.\n\n"
        f"6. اختر القسم الأنسب لهذا الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}\n"
        f"{internal_link_instruction}"
    )

    ai_response = call_gemini_api(prompt, api_key=api_key)
    if not ai_response:
        AIImportLog.objects.create(
            source=None,
            source_url=source_url,
            wp_site=wp_site,
            title=f"تحديث {topic_title}",
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

        author = pick_default_author(ai_settings)
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
            logger.error(f"Error syndicating {topic_title} article to WP site {wp_site.name}: {wpe}")

        AIImportLog.objects.create(
            source=None,
            article=article,
            wp_site=wp_site,
            source_url=source_url,
            published_url=published_url or '',
            title=new_title,
            status='success' if published_url else 'failed',
            error_message='' if published_url else 'فشل النشر على ووردبريس'
        )
        return bool(published_url)
    except Exception as ex:
        logger.error(f"Failed to generate {topic_title} article for {wp_site.name}: {ex}")
        AIImportLog.objects.create(
            source=None,
            source_url=source_url,
            wp_site=wp_site,
            title=f"تحديث {topic_title}",
            status='failed',
            error_message=f"فشل صياغة خبر {topic_title} لـ {wp_site.name}: {str(ex)}"
        )
        return False


def generate_arab_currencies_article_for_site(wp_site, currency_items, source_url, ai_settings, api_key, allowed_cats, categories_list_str):
    """
    Writes and publishes a fresh article covering Arab currencies' exchange
    rates (buy/sell) against the Egyptian pound to a single WordPress site,
    using the exact official numbers in currency_items. Mirrors the gold/
    dollar article style. Returns True on a successful publish, False otherwise.
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

    numbers_lines = []
    for currency in currency_items:
        line = f"- {currency['name']}: شراء {currency['buy_rate']} جنيه، بيع {currency['sell_rate']} جنيه"
        if currency.get('change_yesterday'):
            direction = "ارتفاع" if currency['change_yesterday'] > 0 else "انخفاض"
            line += f" (بـ{direction} {abs(round(currency['change_yesterday'], 3))} جنيه مقارنة بالأمس)"
        numbers_lines.append(line)
    numbers_block = "\n".join(numbers_lines)

    prompt = (
        f"بصفتك محررًا اقتصاديًا محترفًا باللغة العربية، اكتب خبرًا صحفيًا محدَّثًا عن أسعار صرف العملات العربية "
        f"والأجنبية مقابل الجنيه المصري اليوم، معتمداً حصرياً على الأرقام الرسمية التالية الصادرة عن مركز معلومات "
        f"مجلس الوزراء المصري لحظة كتابة الخبر - اذكرها كما هي تماماً دون تقريب أو اختراع أي رقم بديل:\n"
        f"{numbers_block}\n\n"
        f"الرجاء الالتزام التام بالتعليمات التالية:\n"
        f"1. اكتب بأسلوب صحفي اقتصادي مباشر وواضح، بين 200 و350 كلمة. {READABILITY_INSTRUCTION}\n"
        f"2. قم بصياغة عنوان جذاب يذكر تحديث أسعار العملات العربية والأجنبية اليوم.\n"
        f"3. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
        f"4. اذكر سعري الشراء والبيع لكل عملة كما وردا أعلاه بدقة، واذكر المقارنة بالأمس فقط إن وردت في الأرقام، "
        f"ولا تخترع أي مقارنة أو نسبة غير مذكورة.\n"
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
        f"(مثال: \"سعر الريال السعودي اليوم\"، \"سعر الدرهم الإماراتي مقابل الجنيه المصري\").\n\n"
        f"6. اختر القسم الأنسب لهذا الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}\n"
        f"{internal_link_instruction}"
    )

    ai_response = call_gemini_api(prompt, api_key=api_key)
    if not ai_response:
        AIImportLog.objects.create(
            source=None,
            source_url=source_url,
            wp_site=wp_site,
            title="تحديث أسعار العملات العربية والأجنبية",
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

        author = pick_default_author(ai_settings)
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
            logger.error(f"Error syndicating Arab currencies article to WP site {wp_site.name}: {wpe}")

        AIImportLog.objects.create(
            source=None,
            article=article,
            wp_site=wp_site,
            source_url=source_url,
            published_url=published_url or '',
            title=new_title,
            status='success' if published_url else 'failed',
            error_message='' if published_url else 'فشل النشر على ووردبريس'
        )
        return bool(published_url)
    except Exception as ex:
        logger.error(f"Failed to generate Arab currencies article for {wp_site.name}: {ex}")
        AIImportLog.objects.create(
            source=None,
            source_url=source_url,
            wp_site=wp_site,
            title="تحديث أسعار العملات العربية والأجنبية",
            status='failed',
            error_message=f"فشل صياغة خبر أسعار العملات العربية لـ {wp_site.name}: {str(ex)}"
        )
        return False


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

                # Set alt text (accessibility + SEO) - the upload above sends raw
                # binary data so alt_text can't ride along in the same request;
                # WordPress accepts it via a follow-up PATCH to the same media item.
                try:
                    requests.post(
                        f"{media_url}/{featured_media_id}",
                        auth=auth,
                        json={'alt_text': article.title},
                        timeout=10,
                    )
                except Exception as alt_e:
                    logger.warning(f"Failed to set alt text for media {featured_media_id} on {wp_site.name}: {alt_e}")
            else:
                logger.error(f"Failed to upload media to WP site {wp_site.name}: {response.text}")
        except Exception as e:
            logger.error(f"Error uploading media to WP: {e}")

    # 2. Map categories - a local category can map to a single WP category ID
    # (legacy format, e.g. {"اقتصاد": 5}) or to a primary category plus extra
    # secondary ones (e.g. {"اقتصاد": {"primary": 5, "secondary": [12, 20]}}).
    wp_categories = []
    primary_category_id = None
    cat_mappings = wp_site.get_category_mappings()
    local_cat_name = article.category.name if article.category else ""

    mapping = cat_mappings.get(local_cat_name)
    if isinstance(mapping, dict):
        try:
            if mapping.get('primary') is not None:
                primary_category_id = int(mapping['primary'])
                wp_categories.append(primary_category_id)
        except (ValueError, TypeError):
            pass
        for secondary_id in mapping.get('secondary') or []:
            try:
                wp_categories.append(int(secondary_id))
            except (ValueError, TypeError):
                pass
    elif mapping is not None:
        try:
            primary_category_id = int(mapping)
            wp_categories.append(primary_category_id)
        except (ValueError, TypeError):
            pass


    # 3. Prepare post body
    payload = {
        'title': article.title,
        'content': article.body,
        'excerpt': article.excerpt or '',
        'status': 'publish',
    }
    wp_author_ids = wp_site.get_wp_author_ids_list()
    if wp_author_ids:
        payload['author'] = random.choice(wp_author_ids)
    if featured_media_id:
        payload['featured_media'] = featured_media_id
    if wp_categories:
        payload['categories'] = wp_categories
    if extra_tag_names:
        tag_ids = get_or_create_wp_tag_ids(wp_site, extra_tag_names, auth)
        if tag_ids:
            payload['tags'] = tag_ids
    if focus_keyword or meta_description or primary_category_id:
        payload['meta'] = {}
        if focus_keyword:
            payload['meta']['_yoast_wpseo_focuskw'] = focus_keyword
        if meta_description:
            payload['meta']['_yoast_wpseo_metadesc'] = meta_description
        if primary_category_id:
            payload['meta']['_yoast_wpseo_primary_category'] = primary_category_id

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

        author = pick_default_author(ai_settings)
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


def generate_silver_price_article_for_site(wp_site, silver_data, comparison_text, ai_settings, api_key, allowed_cats, categories_list_str):
    """
    Writes and publishes a fresh silver-price article to a single WordPress site,
    using the exact real numbers in silver_data rather than any AI-invented figures.
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
        f"بصفتك محررًا اقتصاديًا محترفًا باللغة العربية، اكتب خبرًا صحفيًا محدَّثًا عن سعر الفضة اليوم في مصر، "
        f"معتمداً حصرياً على الأرقام الحقيقية التالية المأخوذة من السوق العالمية لحظة كتابة الخبر - "
        f"اذكرها كما هي تماماً دون تقريب أو اختراع أي رقم بديل:\n"
        f"- سعر أوقية الفضة عالمياً: {silver_data['spot_usd_per_oz']} دولار أمريكي\n"
        f"- سعر صرف الدولار: {silver_data['usd_to_egp']} جنيه مصري\n"
        f"- سعر جرام الفضة الخالصة (عيار 999): {silver_data['price_999_egp']} جنيه مصري\n"
        f"- سعر جرام الفضة (عيار 925 -- إسترليني): {silver_data['price_925_egp']} جنيه مصري"
        f"{comparison_line}\n\n"
        f"الرجاء الالتزام التام بالتعليمات التالية:\n"
        f"1. اكتب بأسلوب صحفي اقتصادي مباشر وواضح، بين 250 و400 كلمة. {READABILITY_INSTRUCTION}\n"
        f"2. قم بصياغة عنوان جذاب يذكر تحديث سعر الفضة اليوم.\n"
        f"3. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
        f"4. أضف في نهاية الخبر فقرة قصيرة بعنوان \"نظرة عامة على السوق\" تصف الاتجاه العام لحركة الفضة عالمياً "
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
        f"(مثال: \"سعر الفضة اليوم\"، \"سعر جرام الفضة في مصر\").\n\n"
        f"6. اختر القسم الأنسب لهذا الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}\n"
        f"{internal_link_instruction}"
    )

    ai_response = call_gemini_api(prompt, api_key=api_key)
    if not ai_response:
        AIImportLog.objects.create(
            source=None,
            source_url=SILVER_SPOT_API_URL,
            wp_site=wp_site,
            title="تحديث سعر الفضة",
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

        author = pick_default_author(ai_settings)
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
            logger.error(f"Error syndicating silver price article to WP site {wp_site.name}: {wpe}")

        AIImportLog.objects.create(
            source=None,
            article=article,
            wp_site=wp_site,
            source_url=SILVER_SPOT_API_URL,
            published_url=published_url or '',
            title=new_title,
            status='success' if published_url else 'failed',
            error_message='' if published_url else 'فشل النشر على ووردبريس'
        )
        return bool(published_url)
    except Exception as ex:
        logger.error(f"Failed to generate silver price article for {wp_site.name}: {ex}")
        AIImportLog.objects.create(
            source=None,
            source_url=SILVER_SPOT_API_URL,
            wp_site=wp_site,
            title="تحديث سعر الفضة",
            status='failed',
            error_message=f"فشل صياغة خبر سعر الفضة لـ {wp_site.name}: {str(ex)}"
        )
        return False


def generate_dollar_price_article_for_site(wp_site, dollar_data, comparison_text, ai_settings, api_key, allowed_cats, categories_list_str):
    """
    Writes and publishes a fresh dollar-exchange-rate article to a single WordPress
    site, using the exact real number in dollar_data rather than any AI-invented figure.
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
        f"بصفتك محررًا اقتصاديًا محترفًا باللغة العربية، اكتب خبرًا صحفيًا محدَّثًا عن سعر صرف الدولار اليوم في مصر، "
        f"معتمداً حصرياً على الرقم الحقيقي التالي المأخوذ من السوق لحظة كتابة الخبر - "
        f"اذكره كما هو تماماً دون تقريب أو اختراع رقم بديل:\n"
        f"- سعر صرف الدولار الأمريكي: {dollar_data['usd_to_egp']} جنيه مصري"
        f"{comparison_line}\n\n"
        f"الرجاء الالتزام التام بالتعليمات التالية:\n"
        f"1. اكتب بأسلوب صحفي اقتصادي مباشر وواضح، بين 200 و350 كلمة. {READABILITY_INSTRUCTION}\n"
        f"2. قم بصياغة عنوان جذاب يذكر تحديث سعر الدولار اليوم.\n"
        f"3. اكتب ملخصًا قصيرًا وموجزًا للخبر (Excerpt) مكون من سطرين إلى ثلاثة أسطر.\n"
        f"4. أضف في نهاية الخبر فقرة قصيرة بعنوان \"نظرة عامة على السوق\" تصف الاتجاه العام لحركة سعر الصرف "
        f"بصياغة عامة ومتحفظة، على أن تنتهي الفقرة حرفياً بجملة توضيحية مشابهة لـ: \"هذه قراءة عامة لحركة السوق "
        f"ولا تُعد توصية استثمارية.\" لا تذكر أي أرقام أو مستويات أو نسب مستقبلية مختلَقة، فقط وصف عام للاتجاه.\n"
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
        f"(مثال: \"سعر الدولار اليوم\"، \"سعر الدولار مقابل الجنيه المصري\").\n\n"
        f"6. اختر القسم الأنسب لهذا الخبر من قائمة الأقسام المتاحة التالية حصرياً:\n{categories_list_str}\n"
        f"{internal_link_instruction}"
    )

    ai_response = call_gemini_api(prompt, api_key=api_key)
    if not ai_response:
        AIImportLog.objects.create(
            source=None,
            source_url=GOLD_FX_API_URL,
            wp_site=wp_site,
            title="تحديث سعر الدولار",
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

        author = pick_default_author(ai_settings)
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
            logger.error(f"Error syndicating dollar price article to WP site {wp_site.name}: {wpe}")

        AIImportLog.objects.create(
            source=None,
            article=article,
            wp_site=wp_site,
            source_url=GOLD_FX_API_URL,
            published_url=published_url or '',
            title=new_title,
            status='success' if published_url else 'failed',
            error_message='' if published_url else 'فشل النشر على ووردبريس'
        )
        return bool(published_url)
    except Exception as ex:
        logger.error(f"Failed to generate dollar price article for {wp_site.name}: {ex}")
        AIImportLog.objects.create(
            source=None,
            source_url=GOLD_FX_API_URL,
            wp_site=wp_site,
            title="تحديث سعر الدولار",
            status='failed',
            error_message=f"فشل صياغة خبر سعر الدولار لـ {wp_site.name}: {str(ex)}"
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
    # Separate from wp_site_counts (today's total): tracks how many articles this
    # specific cycle invocation has generated per site, capped by articles_per_run.
    wp_site_run_counts = {}

    # Precompute this cycle's regular-news (RSS/Trends) cap per WP site once, so
    # it stays consistent across every source/item processed in this cycle. Sites
    # with schedule slots configured only get regular news when a "regular" slot
    # is due right now (Cairo time), capped by that slot's own count; sites with
    # no slots keep the legacy fixed articles_per_run cap on every cycle run.
    regular_news_caps = {}
    regular_due_slots = {}
    for _site in WordPressSite.objects.filter(is_active=True):
        _cap, _due_slot = get_regular_news_run_cap(_site)
        regular_news_caps[_site.id] = _cap
        if _due_slot:
            regular_due_slots[_site.id] = _due_slot

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
            # Gold/silver/dollar price news comes exclusively from the dedicated
            # live gold-price generator, never from the RSS rewrite pipeline.
            if is_excluded_price_topic(item['title'], item.get('description')):
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
                    
                    author = pick_default_author(ai_settings)
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
                    if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit or wp_site_run_counts.get(wp_site.id, 0) >= regular_news_caps.get(wp_site.id, 0):
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
                        
                        author = pick_default_author(ai_settings)
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
                            wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                            if wp_site.id in regular_due_slots:
                                mark_slot_run(regular_due_slots[wp_site.id], 'regular')

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

    # Live gold price articles: independent of RSS sources. Sites with no
    # schedule slots keep firing every cycle (legacy behavior); sites with
    # slots only fire when a "gold" slot is due right now (Cairo time).
    gold_price_sites, gold_due_slots, _ = sites_due_for_type('gold', 'generate_gold_price_articles')
    if gold_price_sites:
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
                if wp_site.id not in gold_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_gold_price_article_for_site(
                    wp_site, gold_data, comparison_text, ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in gold_due_slots:
                        mark_slot_run(gold_due_slots[wp_site.id], 'gold')
        else:
            logger.error("Failed to fetch live gold price data; skipping gold price article generation this cycle.")

    silver_price_sites, silver_due_slots, silver_legacy_used = sites_due_for_type(
        'silver', 'generate_silver_price_articles', ai_settings, 'last_silver_price_at'
    )
    if silver_price_sites:
        silver_data = fetch_live_silver_prices()
        if silver_data:
            comparison_text = ""
            if ai_settings.last_silver_price_egp:
                diff = silver_data['price_999_egp'] - ai_settings.last_silver_price_egp
                if abs(diff) >= 0.5:
                    direction = "ارتفع" if diff > 0 else "تراجع"
                    comparison_text = (
                        f"- مقارنة حقيقية بآخر تحديث مسجَّل: {direction} سعر جرام الفضة الخالصة بمقدار "
                        f"{abs(round(diff, 2))} جنيه مصري (اذكر هذه المقارنة بدقة كما هي)."
                    )
            ai_settings.last_silver_price_egp = silver_data['price_999_egp']
            if silver_legacy_used:
                ai_settings.last_silver_price_at = silver_data['timestamp']
                ai_settings.save(update_fields=['last_silver_price_egp', 'last_silver_price_at'])
            else:
                ai_settings.save(update_fields=['last_silver_price_egp'])

            for wp_site in silver_price_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in silver_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_silver_price_article_for_site(
                    wp_site, silver_data, comparison_text, ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in silver_due_slots:
                        mark_slot_run(silver_due_slots[wp_site.id], 'silver')
        else:
            logger.error("Failed to fetch live silver price data; skipping silver price article generation this cycle.")

    dollar_price_sites, dollar_due_slots, _ = sites_due_for_type('dollar', 'generate_dollar_price_articles')
    if dollar_price_sites:
        dollar_data = fetch_live_dollar_price()
        if dollar_data:
            comparison_text = ""
            if ai_settings.last_dollar_price_egp:
                diff = dollar_data['usd_to_egp'] - ai_settings.last_dollar_price_egp
                if abs(diff) >= 0.01:
                    direction = "ارتفع" if diff > 0 else "تراجع"
                    comparison_text = (
                        f"- مقارنة حقيقية بآخر تحديث مسجَّل: {direction} سعر صرف الدولار بمقدار "
                        f"{abs(round(diff, 2))} جنيه مصري (اذكر هذه المقارنة بدقة كما هي)."
                    )
            ai_settings.last_dollar_price_egp = dollar_data['usd_to_egp']
            ai_settings.last_dollar_price_at = dollar_data['timestamp']
            ai_settings.save(update_fields=['last_dollar_price_egp', 'last_dollar_price_at'])

            for wp_site in dollar_price_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in dollar_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_dollar_price_article_for_site(
                    wp_site, dollar_data, comparison_text, ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in dollar_due_slots:
                        mark_slot_run(dollar_due_slots[wp_site.id], 'dollar')
        else:
            logger.error("Failed to fetch live dollar price data; skipping dollar price article generation this cycle.")

    iron_sites, iron_due_slots, iron_legacy_used = sites_due_for_type(
        'iron', 'generate_iron_price_articles', ai_settings, 'last_iron_price_at'
    )
    if iron_sites:
        iron_data = fetch_idsc_indicator('iron')
        iron_investment_data = fetch_idsc_indicator('iron_investment')
        if iron_data and iron_investment_data:
            if iron_legacy_used:
                ai_settings.last_iron_price_at = timezone.now()
                ai_settings.save(update_fields=['last_iron_price_at'])
            source_url = f"{IDSC_API_BASE}/PricesData/GetMainIndicatorData/{IDSC_INDICATOR_IDS['iron']}"
            iron_items = [
                ("حديد عز", iron_data),
                ("حديد إستثماري", iron_investment_data),
            ]
            for wp_site in iron_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in iron_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_official_commodity_article_for_site(
                    wp_site, "أسعار الحديد (عز واستثماري)", iron_items, source_url,
                    ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in iron_due_slots:
                        mark_slot_run(iron_due_slots[wp_site.id], 'iron')
        else:
            logger.error("Failed to fetch official iron price data; skipping this cycle.")

    cement_sites, cement_due_slots, cement_legacy_used = sites_due_for_type(
        'cement', 'generate_cement_price_articles', ai_settings, 'last_cement_price_at'
    )
    if cement_sites:
        cement_data = fetch_idsc_indicator('cement')
        if cement_data:
            if cement_legacy_used:
                ai_settings.last_cement_price_at = timezone.now()
                ai_settings.save(update_fields=['last_cement_price_at'])
            source_url = f"{IDSC_API_BASE}/PricesData/GetMainIndicatorData/{IDSC_INDICATOR_IDS['cement']}"
            for wp_site in cement_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in cement_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_official_commodity_article_for_site(
                    wp_site, "سعر الإسمنت (الرمادي)", [("الأسمنت الرمادي", cement_data)], source_url,
                    ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in cement_due_slots:
                        mark_slot_run(cement_due_slots[wp_site.id], 'cement')
        else:
            logger.error("Failed to fetch official cement price data; skipping this cycle.")

    poultry_sites, poultry_due_slots, poultry_legacy_used = sites_due_for_type(
        'poultry', 'generate_poultry_price_articles', ai_settings, 'last_poultry_price_at'
    )
    if poultry_sites:
        poultry_data = fetch_idsc_indicator('poultry')
        if poultry_data:
            if poultry_legacy_used:
                ai_settings.last_poultry_price_at = timezone.now()
                ai_settings.save(update_fields=['last_poultry_price_at'])
            source_url = f"{IDSC_API_BASE}/PricesData/GetMainIndicatorData/{IDSC_INDICATOR_IDS['poultry']}"
            for wp_site in poultry_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in poultry_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_official_commodity_article_for_site(
                    wp_site, "سعر الدواجن (الفراخ)", [("الدواجن الطازجة", poultry_data)], source_url,
                    ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in poultry_due_slots:
                        mark_slot_run(poultry_due_slots[wp_site.id], 'poultry')
        else:
            logger.error("Failed to fetch official poultry price data; skipping this cycle.")

    fish_sites, fish_due_slots, fish_legacy_used = sites_due_for_type(
        'fish', 'generate_fish_price_articles', ai_settings, 'last_fish_price_at'
    )
    if fish_sites:
        fish_data = fetch_idsc_indicator('fish')
        fish_tilapia_data = fetch_idsc_indicator('fish_tilapia')
        fish_shrimp_data = fetch_idsc_indicator('fish_shrimp')
        fish_sardine_data = fetch_idsc_indicator('fish_sardine')
        if fish_data and fish_tilapia_data and fish_shrimp_data and fish_sardine_data:
            if fish_legacy_used:
                ai_settings.last_fish_price_at = timezone.now()
                ai_settings.save(update_fields=['last_fish_price_at'])
            source_url = f"{IDSC_API_BASE}/PricesData/GetMainIndicatorData/{IDSC_INDICATOR_IDS['fish']}"
            fish_items = [
                ("السمك (متوسط عام)", fish_data),
                ("البلطي", fish_tilapia_data),
                ("الجمبري", fish_shrimp_data),
                ("السردين المجمد", fish_sardine_data),
            ]
            for wp_site in fish_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in fish_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_official_commodity_article_for_site(
                    wp_site, "أسعار الأسماك (بلطي، جمبري، سردين)", fish_items, source_url,
                    ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in fish_due_slots:
                        mark_slot_run(fish_due_slots[wp_site.id], 'fish')
        else:
            logger.error("Failed to fetch official fish price data; skipping this cycle.")

    vegetable_sites, vegetable_due_slots, vegetable_legacy_used = sites_due_for_type(
        'vegetable', 'generate_vegetable_price_articles', ai_settings, 'last_vegetable_price_at'
    )
    if vegetable_sites:
        tomatoes_data = fetch_idsc_indicator('tomatoes')
        potatoes_data = fetch_idsc_indicator('potatoes')
        onions_data = fetch_idsc_indicator('onions')
        if tomatoes_data and potatoes_data and onions_data:
            if vegetable_legacy_used:
                ai_settings.last_vegetable_price_at = timezone.now()
                ai_settings.save(update_fields=['last_vegetable_price_at'])
            source_url = f"{IDSC_API_BASE}/PricesData/GetMainIndicatorData/{IDSC_INDICATOR_IDS['tomatoes']}"
            vegetable_items = [
                ("الطماطم", tomatoes_data),
                ("البطاطس", potatoes_data),
                ("البصل", onions_data),
            ]
            for wp_site in vegetable_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in vegetable_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_official_commodity_article_for_site(
                    wp_site, "أسعار الخضار (طماطم، بطاطس، بصل)", vegetable_items, source_url,
                    ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in vegetable_due_slots:
                        mark_slot_run(vegetable_due_slots[wp_site.id], 'vegetable')
        else:
            logger.error("Failed to fetch official vegetable price data; skipping this cycle.")

    arab_currency_sites, arab_currency_due_slots, arab_currency_legacy_used = sites_due_for_type(
        'arab_currencies', 'generate_arab_currencies_articles', ai_settings, 'last_arab_currencies_at'
    )
    if arab_currency_sites:
        currency_data = fetch_arab_currency_rates()
        if currency_data:
            if arab_currency_legacy_used:
                ai_settings.last_arab_currencies_at = timezone.now()
                ai_settings.save(update_fields=['last_arab_currencies_at'])
            source_url = f"{IDSC_API_BASE}/PricesData/GetCurrencyExchange"
            for wp_site in arab_currency_sites:
                if generated_count >= limit:
                    break
                if wp_site_counts.get(wp_site.id, 0) >= wp_site.daily_limit:
                    continue
                if wp_site.id not in arab_currency_due_slots and wp_site_run_counts.get(wp_site.id, 0) >= wp_site.articles_per_run:
                    continue
                success = generate_arab_currencies_article_for_site(
                    wp_site, currency_data, source_url, ai_settings, api_key, allowed_cats, categories_list_str
                )
                if success:
                    wp_site_counts[wp_site.id] = wp_site_counts.get(wp_site.id, 0) + 1
                    wp_site_run_counts[wp_site.id] = wp_site_run_counts.get(wp_site.id, 0) + 1
                    generated_count += 1
                    if wp_site.id in arab_currency_due_slots:
                        mark_slot_run(arab_currency_due_slots[wp_site.id], 'arab_currencies')
        else:
            logger.error("Failed to fetch official Arab currency exchange rates; skipping this cycle.")

    # Update last run timestamp
    ai_settings.last_run = timezone.now()
    ai_settings.save()
    
    return generated_count
