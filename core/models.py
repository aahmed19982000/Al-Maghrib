from django.db import models
from django.contrib.auth.models import User

class SiteSettings(models.Model):
    site_name = models.CharField(max_length=255, default="Al Maghrib")
    logo = models.ImageField(upload_to='site/', blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    contact_phone = models.CharField(max_length=50, blank=True, null=True)
    seo_title = models.CharField(max_length=255, blank=True, null=True)
    seo_description = models.TextField(blank=True, null=True)
    google_analytics_id = models.CharField(max_length=50, blank=True, null=True, help_text="Google Analytics Tracking ID (e.g. G-XXXXXXX)")
    
    # Header and Footer Settings
    footer_description = models.TextField(blank=True, null=True, verbose_name="وصف الفوتر", help_text="نبذة تعريفية قصيرة تظهر في أسفل الموقع.")
    facebook_url = models.URLField(blank=True, null=True, verbose_name="رابط فيسبوك")
    twitter_url = models.URLField(blank=True, null=True, verbose_name="رابط تويتر / X")
    instagram_url = models.URLField(blank=True, null=True, verbose_name="رابط إنستجرام")
    youtube_url = models.URLField(blank=True, null=True, verbose_name="رابط يوتيوب")
    
    navbar_categories = models.ManyToManyField('news.Category', blank=True, related_name='navbar_settings', verbose_name="أقسام القائمة العلوية (Header)")
    footer_categories = models.ManyToManyField('news.Category', blank=True, related_name='footer_settings', verbose_name="أقسام أسفل الموقع (Footer)")

    cached_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Enforce singleton
        self.pk = 1
        from core.utils import optimize_image_field
        optimize_image_field(self, 'logo', max_size=(300, 100), quality=85)
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.site_name

class Advertisement(models.Model):
    SLOT_CHOICES = (
        ('header', 'Header Banner'),
        ('sidebar', 'Sidebar Banner'),
        ('inline', 'Inline Content Banner'),
    )
    title = models.CharField(max_length=255)
    image = models.ImageField(upload_to='ads/', blank=True, null=True)
    script_html = models.TextField(blank=True, null=True, help_text="Custom HTML/JS code for ad networks like AdSense")
    slot = models.CharField(max_length=50, choices=SLOT_CHOICES)
    link_url = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.title} ({self.get_slot_display()})"

    def save(self, *args, **kwargs):
        from core.utils import optimize_image_field
        optimize_image_field(self, 'image', max_size=(1200, 600), quality=85)
        super().save(*args, **kwargs)

from taggit.managers import TaggableManager
import uuid

class Newsletter(models.Model):
    email = models.EmailField(unique=True)
    is_confirmed = models.BooleanField(default=False)
    token = models.CharField(max_length=100, blank=True, null=True, default=uuid.uuid4)
    tags = TaggableManager(blank=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email

class PushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True, related_name='push_subscriptions')
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Push Subscription for {self.user.username if self.user else 'Anonymous'}"

class HomePageSettings(models.Model):
    # SEO
    seo_title = models.CharField(max_length=255, blank=True, null=True)
    seo_description = models.TextField(blank=True, null=True)
    seo_keywords = models.CharField(max_length=255, blank=True, null=True)

    # Visibility Toggles
    show_breaking_news = models.BooleanField(default=True, verbose_name="عرض الأخبار العاجلة")
    show_slider = models.BooleanField(default=True, verbose_name="عرض معرض الصور")
    show_featured = models.BooleanField(default=True, verbose_name="عرض الأخبار المميزة")
    show_popular = models.BooleanField(default=True, verbose_name="عرض الأخبار الأكثر قراءة")
    show_authors_section = models.BooleanField(default=True, verbose_name="عرض قسم 'أصوات مغاربية'")
    
    # Customization
    authors_section_title = models.CharField(max_length=255, default="أصوات مغاربية", verbose_name="عنوان قسم الكتاب")
    featured_authors = models.ManyToManyField('accounts.AuthorProfile', blank=True, verbose_name="الكتاب المختارون")

    # Display Limits
    slider_count = models.PositiveIntegerField(default=5, verbose_name="عدد أخبار المعرض")
    featured_count = models.PositiveIntegerField(default=4, verbose_name="عدد الأخبار المميزة")
    popular_count = models.PositiveIntegerField(default=5, verbose_name="عدد الأخبار الأكثر قراءة")
    authors_section_order = models.PositiveIntegerField(default=2, verbose_name="ترتيب قسم 'أصوات مغاربية' (يظهر بعد أي قسم)")
    
    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "إعدادات الصفحة الرئيسية"

class HomePageCategory(models.Model):
    STYLE_CHOICES = (
        ('featured_grid', 'شبكة رئيسية (Featured Grid)'),
        ('dark_cards', 'بطاقات داكنة (Dark Cards)'),
        ('mixed_grid', 'شبكة مختلطة (Mixed Grid)'),
        ('tall_cards', 'بطاقات طولية (Tall Cards)'),
        ('simple_cards', 'بطاقات بسيطة (Simple Cards)'),
        ('country_cards', 'بطاقات دول (Country Cards)'),
        ('grid', 'شبكة عادية (Grid)'),
        ('list', 'قائمة جانبية (List)'),
    )
    category = models.ForeignKey('news.Category', on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)
    design_style = models.CharField(max_length=20, choices=STYLE_CHOICES, default='grid')
    article_count = models.PositiveIntegerField(default=4)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.category.name} - {self.get_design_style_display()}"
