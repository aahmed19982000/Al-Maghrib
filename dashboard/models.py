from django.db import models
from django.contrib.auth.models import User

class ArticleRevision(models.Model):
    article = models.ForeignKey('news.Article', on_delete=models.CASCADE, related_name='revisions')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='article_revisions')
    content_snapshot = models.TextField(help_text="Full HTML/text content snapshot at revision time")
    created_at = models.DateTimeField(auto_now_add=True)
    commit_message = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Revision of {self.article.title} at {self.created_at}"

class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    action_type = models.CharField(max_length=100)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.action_type} at {self.timestamp}"

class DashboardWidget(models.Model):
    WIDGET_TYPES = (
        ('stats', 'Statistics Widget'),
        ('list', 'Recent Content List'),
        ('chart', 'Analytics Chart'),
    )
    title = models.CharField(max_length=100)
    widget_type = models.CharField(max_length=50, choices=WIDGET_TYPES)
    config = models.JSONField(default=dict, blank=True, help_text="Configuration keys and values for widget layout")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.get_widget_type_display()})"
