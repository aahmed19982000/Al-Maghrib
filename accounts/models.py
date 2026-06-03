from django.db import models
from django.contrib.auth.models import User

from django.utils import timezone

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def save(self, *args, **kwargs):
        from core.utils import optimize_image_field
        optimize_image_field(self, 'avatar', max_size=(400, 400), quality=85)
        super().save(*args, **kwargs)

class AuthorProfile(models.Model):
    ROLE_CHOICES = (
        ('writer', 'Writer'),
        ('editor', 'Editor'),
        ('admin', 'Admin/Chief Editor'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='author_profile')
    display_name = models.CharField(max_length=150, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    avatar = models.ImageField(upload_to='authors/', blank=True, null=True)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='writer')
    twitter = models.URLField(blank=True, null=True)
    linkedin = models.URLField(blank=True, null=True)
    email_public = models.EmailField(blank=True, null=True)
    specialization = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    joined_date = models.DateField(default=timezone.localdate)
    
    # Custom permissions
    can_publish_directly = models.BooleanField(default=False)
    can_edit_others = models.BooleanField(default=False)
    can_delete_articles = models.BooleanField(default=False)

    @property
    def articles_count(self):
        return self.user.articles.filter(status='published').count()

    @property
    def total_views(self):
        from django.db.models import Sum
        return self.user.articles.filter(status='published').aggregate(Sum('views_count'))['views_count__sum'] or 0

    def __str__(self):
        return self.display_name or self.user.get_full_name() or self.user.username

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('news:author_detail', kwargs={'pk': self.pk})

    def save(self, *args, **kwargs):
        from core.utils import optimize_image_field
        optimize_image_field(self, 'avatar', max_size=(400, 400), quality=85)
        super().save(*args, **kwargs)

class EditorLog(models.Model):
    editor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='editor_logs')
    action = models.CharField(max_length=255)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    object_name = models.CharField(max_length=255, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.editor.username if self.editor else 'System'} - {self.action} on {self.object_name} at {self.timestamp}"
