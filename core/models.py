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
