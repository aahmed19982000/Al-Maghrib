"""
Generates a social-media "share card" image for a published article (large
cover photo + bold Arabic headline + the WordPress site's own logo and brand
colors) and, if the site has Facebook credentials configured, publishes it
automatically to that site's Facebook Page.

Design notes:
- Proper Arabic shaping/bidi reordering needs either Pillow's raqm/HarfBuzz
  backend (a system-level dependency, libraqm, not guaranteed to be present
  everywhere) or a manual fallback. This module detects raqm support at
  import time (PIL.features.check('raqm')) and picks accordingly:
    * raqm available: fonts are loaded with layout_engine=RAQM and raw
      logical text is drawn directly with direction='rtl' - Pillow does
      correct shaping/reordering itself, which also gives nicer results
      (proper contextual ligatures).
    * raqm unavailable: text is manually reshaped+reordered via
      arabic_reshaper + python-bidi before drawing with the BASIC layout
      engine - a pure-Python fallback that works anywhere Pillow does.
  Mixing the two (drawing manually-reshaped text through a raqm-enabled
  font) double-processes the string and garbles it, so the two paths must
  stay mutually exclusive - every text measurement/draw call below goes
  through _measure_line()/_draw_rtl_line() rather than calling
  draw.textlength()/draw.text() directly.
- The bundled headline font (Amiri-Bold.ttf, SIL Open Font License) was
  chosen because - unlike some modern variable fonts - it ships full glyph
  coverage for the Arabic Presentation Forms block that the manual fallback
  reshapes text into, so headlines render correctly even without raqm.
- Every public entry point here is defensive: failures never raise up into
  the main article-generation/publishing flow, they just log and return a
  failed SocialSharePost (or None).
"""
import io
import logging

import arabic_reshaper
import requests
from bidi.algorithm import get_display
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont, features

logger = logging.getLogger(__name__)

CANVAS_SIZE = (1080, 1080)
FONT_PATH = str(settings.BASE_DIR / 'static' / 'fonts' / 'Amiri-Bold.ttf')

FACEBOOK_GRAPH_VERSION = 'v19.0'

# Detected once at import time - see module docstring for why this matters.
RAQM_AVAILABLE = features.check('raqm')


# ---------------------------------------------------------------------------
# Arabic text shaping helpers
# ---------------------------------------------------------------------------

def _shape(text):
    """Reshapes+reorders a logical Arabic string into visual glyph order (non-raqm fallback only)."""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def _load_font(size, font_path=FONT_PATH):
    layout = ImageFont.Layout.RAQM if RAQM_AVAILABLE else ImageFont.Layout.BASIC
    return ImageFont.truetype(font_path, size, layout_engine=layout)


def _measure_line(draw, text, font):
    """Pixel width of logical-order `text` as it will actually be drawn."""
    if RAQM_AVAILABLE:
        return draw.textlength(text, font=font, direction='rtl')
    return draw.textlength(_shape(text), font=font)


def _draw_rtl_line(draw, right_x, y, text, font, fill):
    """Draws one line of logical-order Arabic text, right-aligned to right_x."""
    if RAQM_AVAILABLE:
        draw.text((right_x, y), text, font=font, fill=fill, direction='rtl', language='ar', anchor='ra')
    else:
        shaped = _shape(text)
        w = draw.textlength(shaped, font=font)
        draw.text((right_x - w, y), shaped, font=font, fill=fill)


def _wrap_arabic_text(draw, text, font, max_width, max_lines=None):
    """
    Word-wraps `text` (logical order) so each resulting line fits within
    max_width pixels once rendered. Returns logical-order line strings -
    shaping/reordering happens later, at draw time.
    """
    words = text.split()
    lines = []
    current = []
    for word in words:
        candidate = current + [word]
        w = _measure_line(draw, ' '.join(candidate), font)
        if w <= max_width or not current:
            current = candidate
        else:
            lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))

    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        words_last = lines[-1].split()
        while words_last:
            candidate_text = ' '.join(words_last) + ' …'
            if _measure_line(draw, candidate_text, font) <= max_width:
                break
            words_last.pop()
        lines[-1] = ' '.join(words_last) + ' …'

    return lines


def _fit_font_and_wrap(draw, text, max_width, max_height, start_size, min_size, font_path=FONT_PATH, max_lines=5, line_spacing=1.3):
    """
    Picks the largest font size (between min_size and start_size) for which
    the wrapped headline fits within (max_width, max_height), returning the
    chosen font and its logical-order wrapped lines.
    """
    size = start_size
    while size >= min_size:
        font = _load_font(size, font_path)
        lines = _wrap_arabic_text(draw, text, font, max_width, max_lines=max_lines)
        line_height = int(size * line_spacing)
        total_height = line_height * len(lines)
        if total_height <= max_height:
            return font, lines, line_height
        size -= 4
    font = _load_font(min_size, font_path)
    lines = _wrap_arabic_text(draw, text, font, max_width, max_lines=max_lines)
    return font, lines, int(min_size * line_spacing)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _cover_crop(img, target_w, target_h):
    """Resizes+center-crops img to exactly (target_w, target_h), like CSS object-fit: cover."""
    img = img.convert('RGB')
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _hex_to_rgb(hex_color, default=(13, 148, 136)):
    try:
        hex_color = (hex_color or '').lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join(c * 2 for c in hex_color)
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _paste_logo(canvas, logo_file, center, diameter=150):
    """Pastes the site logo, scaled to fit inside a white circular chip, centered at `center`."""
    if not logo_file:
        return
    try:
        logo_file.open('rb')
        logo = Image.open(logo_file).convert('RGBA')
    except Exception as e:
        logger.warning(f"Could not open site logo for social image: {e}")
        return
    finally:
        try:
            logo_file.close()
        except Exception:
            pass

    chip = Image.new('RGBA', (diameter, diameter), (0, 0, 0, 0))
    chip_draw = ImageDraw.Draw(chip)
    chip_draw.ellipse((0, 0, diameter, diameter), fill=(255, 255, 255, 235))

    pad = int(diameter * 0.18)
    inner = diameter - 2 * pad
    logo.thumbnail((inner, inner), Image.LANCZOS)
    lx = (diameter - logo.width) // 2
    ly = (diameter - logo.height) // 2
    chip.paste(logo, (lx, ly), logo)

    cx, cy = center
    canvas.paste(chip, (cx - diameter // 2, cy - diameter // 2), chip)


def _get_cover_image(article):
    if not article or not article.cover_image:
        return None
    try:
        article.cover_image.open('rb')
        img = Image.open(article.cover_image).convert('RGB')
        img.load()
        return img
    except Exception as e:
        logger.warning(f"Could not open article cover image for social image: {e}")
        return None
    finally:
        try:
            article.cover_image.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def _template_bottom_banner(cover_img, title, wp_site):
    """Full-bleed photo with a solid colored banner across the bottom holding the headline + logo."""
    w, h = CANVAS_SIZE
    primary = _hex_to_rgb(wp_site.social_primary_color)
    canvas = _cover_crop(cover_img, w, h).convert('RGBA')

    banner_h = 360
    overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Soft gradient above the solid banner so the photo doesn't cut abruptly.
    fade_h = 140
    for i in range(fade_h):
        alpha = int(160 * (i / fade_h))
        draw.line([(0, h - banner_h - fade_h + i), (w, h - banner_h - fade_h + i)], fill=(0, 0, 0, alpha))
    draw.rectangle([0, h - banner_h, w, h], fill=(*primary, 235))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    pad_x = 56
    text_top = h - banner_h + 34
    text_max_w = w - 2 * pad_x
    text_max_h = banner_h - 68
    font, lines, line_height = _fit_font_and_wrap(draw, title, text_max_w, text_max_h, start_size=64, min_size=34, max_lines=4)

    y = text_top
    for line in lines:
        _draw_rtl_line(draw, w - pad_x, y, line, font, fill=(255, 255, 255, 255))
        y += line_height

    _paste_logo(canvas, wp_site.social_logo, center=(pad_x + 60, h - banner_h - 60), diameter=120)
    return canvas.convert('RGB')


def _template_boxed_card(cover_img, title, wp_site):
    """Framed photo with a solid-color caption box underneath, logo chip overlapping the seam."""
    w, h = CANVAS_SIZE
    primary = _hex_to_rgb(wp_site.social_primary_color)
    secondary = _hex_to_rgb(wp_site.social_secondary_color)

    canvas = Image.new('RGB', (w, h), secondary)
    border = 28
    photo_h = 640
    photo = _cover_crop(cover_img, w - 2 * border, photo_h)
    canvas.paste(photo, (border, border))

    canvas = canvas.convert('RGBA')
    draw = ImageDraw.Draw(canvas)

    box_top = border + photo_h
    draw.rectangle([0, box_top, w, h], fill=(*primary, 255))

    pad_x = 64
    text_top = box_top + 60
    text_max_w = w - 2 * pad_x
    text_max_h = h - text_top - 60
    font, lines, line_height = _fit_font_and_wrap(draw, title, text_max_w, text_max_h, start_size=58, min_size=30, max_lines=4)

    y = text_top
    for line in lines:
        _draw_rtl_line(draw, w - pad_x, y, line, font, fill=(255, 255, 255, 255))
        y += line_height

    _paste_logo(canvas, wp_site.social_logo, center=(w - 110, box_top), diameter=140)
    return canvas.convert('RGB')


def _template_split_block(cover_img, title, wp_site):
    """Photo occupies the top ~60% of the canvas, a solid color block with a logo tag + headline fills the rest."""
    w, h = CANVAS_SIZE
    primary = _hex_to_rgb(wp_site.social_primary_color)
    secondary = _hex_to_rgb(wp_site.social_secondary_color)

    split_y = 660
    canvas = Image.new('RGB', (w, h), secondary)
    photo = _cover_crop(cover_img, w, split_y)
    canvas.paste(photo, (0, 0))

    canvas = canvas.convert('RGBA')
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, split_y - 6, w, split_y], fill=(*primary, 255))
    draw.rectangle([0, split_y, w, h], fill=(*secondary, 255))

    pad_x = 56
    logo_d = 96
    _paste_logo(canvas, wp_site.social_logo, center=(w - pad_x - logo_d // 2, split_y + 80), diameter=logo_d)

    text_top = split_y + 40
    text_max_w = w - 2 * pad_x - (logo_d + 24 if wp_site.social_logo else 0)
    text_max_h = h - text_top - 40
    font, lines, line_height = _fit_font_and_wrap(draw, title, text_max_w, text_max_h, start_size=56, min_size=30, max_lines=4)

    y = text_top
    for line in lines:
        _draw_rtl_line(draw, w - pad_x, y, line, font, fill=(255, 255, 255, 255))
        y += line_height

    return canvas.convert('RGB')


TEMPLATES = {
    'bottom_banner': _template_bottom_banner,
    'boxed_card': _template_boxed_card,
    'split_block': _template_split_block,
}


def render_social_share_image(article, wp_site):
    """
    Builds the share-card image for `article` styled with `wp_site`'s brand
    colors/logo/template choice. Returns a PIL Image, or None if there's no
    usable cover image to build from.
    """
    cover_img = _get_cover_image(article)
    if cover_img is None:
        return None

    template_fn = TEMPLATES.get(wp_site.social_template, _template_bottom_banner)
    title = (article.title or '').strip()
    return template_fn(cover_img, title, wp_site)


# ---------------------------------------------------------------------------
# Facebook publishing
# ---------------------------------------------------------------------------

def post_image_to_facebook(wp_site, image_bytes, caption):
    """
    Publishes a raw image (bytes) to the WordPress site's linked Facebook
    Page via the Graph API photos endpoint. Returns (post_id, error_message)
    - exactly one of which will be truthy.
    """
    if not wp_site.facebook_auto_publish_enabled:
        return None, "لم يتم ضبط معرّف صفحة فيسبوك أو توكن الوصول لهذا الموقع."

    url = f"https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/{wp_site.facebook_page_id}/photos"
    try:
        response = requests.post(
            url,
            data={'caption': caption, 'access_token': wp_site.facebook_access_token},
            files={'source': ('image.jpg', image_bytes, 'image/jpeg')},
            timeout=30,
        )
        result = response.json()
    except Exception as e:
        logger.error(f"Error posting social image to Facebook for {wp_site.name}: {e}")
        return None, str(e)

    post_id = result.get('post_id') or result.get('id')
    if response.status_code == 200 and post_id:
        return post_id, None

    error_message = (result.get('error') or {}).get('message') or response.text
    logger.error(f"Facebook publish failed for {wp_site.name}: {error_message}")
    return None, error_message


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def generate_and_publish_social_share(article, wp_site, force=False):
    """
    Full pipeline for one (article, wp_site) pair: renders the share image,
    saves it as a SocialSharePost, and - if the site has Facebook
    credentials configured - publishes it automatically to that Page.

    `force=True` (used by the manual "regenerate" action) generates the
    image even if wp_site.social_image_enabled is off; automatic calls from
    the generation pipeline should leave force=False so the per-site toggle
    is respected.

    Never raises - any failure is captured on the returned SocialSharePost
    (or logged and returns None if the post row couldn't even be created).
    """
    from .models import SocialSharePost

    if not force and not wp_site.social_image_enabled:
        return None
    if not article:
        return None

    social_post = SocialSharePost.objects.create(
        wp_site=wp_site,
        article=article,
        article_title=article.title,
        template_used=wp_site.social_template,
        status='generated',
    )

    try:
        image = render_social_share_image(article, wp_site)
        if image is None:
            social_post.status = 'failed'
            social_post.error_message = "لا توجد صورة غلاف صالحة لهذا الخبر لبناء التصميم منها."
            social_post.save(update_fields=['status', 'error_message'])
            return social_post

        buf = io.BytesIO()
        image.save(buf, format='JPEG', quality=90)
        image_bytes = buf.getvalue()

        filename = f"social_{wp_site.pk}_{article.pk}.jpg"
        social_post.generated_image.save(filename, ContentFile(image_bytes), save=False)
        social_post.save(update_fields=['generated_image'])

        if wp_site.facebook_auto_publish_enabled:
            caption = article.title or ''
            post_id, error = post_image_to_facebook(wp_site, image_bytes, caption)
            if post_id:
                social_post.status = 'posted'
                social_post.facebook_post_id = post_id
                social_post.posted_at = timezone.now()
                social_post.save(update_fields=['status', 'facebook_post_id', 'posted_at'])
            else:
                social_post.status = 'failed'
                social_post.error_message = error or 'فشل النشر على فيسبوك.'
                social_post.save(update_fields=['status', 'error_message'])

        return social_post
    except Exception as e:
        logger.error(f"Error generating/publishing social image for article {getattr(article, 'pk', None)} / site {wp_site.name}: {e}")
        try:
            social_post.status = 'failed'
            social_post.error_message = str(e)
            social_post.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
        return social_post
