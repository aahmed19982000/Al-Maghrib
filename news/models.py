from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from mptt.models import MPTTModel, TreeForeignKey
from taggit.managers import TaggableManager

# Soft Delete Manager and QuerySet
class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

class Category(MPTTModel):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, allow_unicode=True)
    icon = models.CharField(max_length=100, blank=True, null=True, help_text="CSS class name or simple icon label")
    parent = TreeForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=20, blank=True, null=True, help_text="Hex color code or class name")

    # Meta SEO fields
    meta_title = models.CharField(max_length=255, blank=True, null=True)
    meta_description = models.TextField(blank=True, null=True)
    meta_keywords = models.CharField(max_length=255, blank=True, null=True)

    class MPTTMeta:
        order_insertion_by = ['order', 'name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('news:category_list', kwargs={'slug': self.slug})

class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True, allow_unicode=True)

    def __str__(self):
        return self.name

class Article(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('review', 'Review'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True)
    body = models.TextField()
    excerpt = models.TextField(blank=True, null=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='articles')
    category = TreeForeignKey(Category, on_delete=models.PROTECT, related_name='articles')
    additional_categories = models.ManyToManyField(Category, related_name='additional_articles', blank=True, help_text="أقسام فرعية إضافية (اختياري)")
    tags = TaggableManager(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    
    is_featured = models.BooleanField(default=False)
    is_breaking = models.BooleanField(default=False)
    auto_translate = models.BooleanField(default=True, help_text="ترجمة تلقائية للإنجليزية (Auto-translate to English)")
    cover_image = models.ImageField(upload_to='articles/', blank=True, null=True)
    views_count = models.PositiveIntegerField(default=0)
    read_time = models.PositiveIntegerField(default=0, help_text="Read time in minutes")
    allow_comments = models.BooleanField(default=True)
    
    # Meta SEO fields
    meta_title = models.CharField(max_length=255, blank=True, null=True)
    meta_desc = models.TextField(blank=True, null=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        permissions = [
            ("can_publish", "Can publish articles"),
            ("can_feature", "Can feature articles"),
        ]

    def save(self, *args, **kwargs):
        if self.status == 'published' and not self.published_at:
            self.published_at = timezone.now()

        # Automatic Pillow Image Compression and WebP Conversion
        from core.utils import optimize_image_field, translate_text, is_html_empty

        optimize_image_field(self, 'cover_image', max_size=(1200, 1200), quality=85)

        # ── Auto-translate Arabic fields → English ──
        # Only runs when the update_fields kwarg does NOT exclude these fields
        # (i.e., not triggered by a simple soft-delete update_fields=['deleted_at'])
        update_fields = kwargs.get('update_fields')
        skip_translation = update_fields is not None and 'title_en' not in update_fields

        if not skip_translation and getattr(self, 'auto_translate', True):
            # Title
            if getattr(self, 'title_ar', None):
                self.title_en = translate_text(self.title_ar)

            # Excerpt
            if getattr(self, 'excerpt_ar', None):
                self.excerpt_en = translate_text(self.excerpt_ar)

            # Body
            if getattr(self, 'body_ar', None):
                self.body_en = translate_text(self.body_ar)

            # SEO meta title
            if getattr(self, 'meta_title_ar', None):
                self.meta_title_en = translate_text(self.meta_title_ar)

            # SEO meta description
            if getattr(self, 'meta_desc_ar', None):
                self.meta_desc_en = translate_text(self.meta_desc_ar)

        super().save(*args, **kwargs)


    def delete(self, *args, **kwargs):
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at'])

    def hard_delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('news:article_detail', kwargs={'slug': self.slug})

class Comment(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    body = models.TextField()
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.user.username} on {self.article.title}"

class Like(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('article', 'user')

    def __str__(self):
        return f"{self.user.username} liked {self.article.title}"

class Bookmark(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='bookmarks')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookmarks')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('article', 'user')

    def __str__(self):
        return f"{self.user.username} bookmarked {self.article.title}"

class RelatedArticle(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='related_from')
    related_article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='related_to')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('article', 'related_article')
        ordering = ['order']

    def __str__(self):
        return f"{self.related_article.title} related to {self.article.title}"

# Cache Invalidation on Publish/Save/Delete
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

@receiver(post_save, sender=Article)
@receiver(post_delete, sender=Article)
@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
def clear_cache_on_change(sender, **kwargs):
    try:
        cache.clear()
    except Exception:
        # Safeguard if cache connection fails in environment
        pass

@receiver(post_save, sender=Article)
def auto_add_to_latest_news(sender, instance, created, **kwargs):
    if created:
        try:
            # You can identify "آخر الأخبار" by its slug or name. Assuming slug is 'آخر-الأخبار'
            latest_category = Category.objects.filter(name_ar__icontains='آخر الأخبار').first()
            if latest_category and instance.category != latest_category:
                instance.additional_categories.add(latest_category)
        except Exception:
            pass
