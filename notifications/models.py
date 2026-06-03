from django.db import models
from django.contrib.auth.models import User

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    verb = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.user.username}: {self.verb}"

class EmailQueue(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    )
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    send_after = models.DateTimeField(blank=True, null=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Email to {self.recipient_email} - {self.subject} ({self.get_status_display()})"

class PushLog(models.Model):
    subscription = models.ForeignKey('core.PushSubscription', on_delete=models.CASCADE, related_name='push_logs')
    notification = models.ForeignKey(Notification, on_delete=models.SET_NULL, null=True, blank=True, related_name='push_logs')
    status = models.CharField(max_length=50)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Push to subscription {self.subscription.id} - Status: {self.status}"
