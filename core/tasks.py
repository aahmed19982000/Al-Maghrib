import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def cleanup_expired_and_deleted_records(self):
    """
    Periodic task (runs daily via Celery Beat) to:
    1. Hard-delete soft-deleted articles older than 30 days.
    2. Delete old notifications older than 30 days.
    3. Mark expired advertisements as inactive.
    """
    try:
        from django.utils import timezone
        from datetime import timedelta

        cutoff_date = timezone.now() - timedelta(days=30)

        # 1. Hard-delete soft-deleted articles older than 30 days
        from news.models import Article
        old_deleted_articles = Article.all_objects.filter(
            deleted_at__isnull=False,
            deleted_at__lt=cutoff_date
        )
        count_articles = old_deleted_articles.count()
        for article in old_deleted_articles:
            article.hard_delete()
        logger.info(f"Hard-deleted {count_articles} soft-deleted articles older than 30 days")

        # 2. Delete old notifications
        from notifications.models import Notification
        count_notifs = Notification.objects.filter(
            created_at__lt=cutoff_date
        ).delete()[0]
        logger.info(f"Deleted {count_notifs} old notifications")

        # 3. Mark expired advertisements as inactive
        from core.models import Advertisement
        count_ads = Advertisement.objects.filter(
            is_active=True,
            end_date__isnull=False,
            end_date__lt=timezone.now()
        ).update(is_active=False)
        logger.info(f"Deactivated {count_ads} expired advertisements")

        return {
            'deleted_articles': count_articles,
            'deleted_notifications': count_notifs,
            'deactivated_ads': count_ads,
        }
    except Exception as exc:
        logger.error(f"Cleanup task failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_newsletter_task(self, subject, body):
    """
    Send a newsletter email to all confirmed subscribers.
    Enqueues individual emails into the EmailQueue for batch processing.
    """
    try:
        from core.models import Newsletter
        from notifications.models import EmailQueue

        subscribers = Newsletter.objects.filter(is_confirmed=True)
        enqueued = 0

        for subscriber in subscribers:
            EmailQueue.objects.create(
                recipient_email=subscriber.email,
                subject=subject,
                body=body,
            )
            enqueued += 1

        logger.info(f"Enqueued {enqueued} newsletter emails for subject: {subject}")
        return {'enqueued': enqueued}
    except Exception as exc:
        logger.error(f"Newsletter enqueue failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True)
def send_daily_newsletter(self):
    """
    Periodic task (runs daily via Celery Beat) to compile and send the daily newsletter.
    Gathers the top 5 published articles from the past 24 hours and sends a digest.
    """
    try:
        from django.utils import timezone
        from datetime import timedelta
        from news.models import Article
        from core.models import Newsletter
        from notifications.models import EmailQueue

        yesterday = timezone.now() - timedelta(hours=24)
        top_articles = Article.objects.filter(
            status='published',
            published_at__gte=yesterday
        ).order_by('-views_count')[:5]

        if not top_articles.exists():
            logger.info("No articles published in the last 24 hours, skipping daily newsletter")
            return {'status': 'skipped', 'reason': 'no_articles'}

        # Build the newsletter body
        lines = ["أهم أخبار اليوم من المغرب العربي:\n"]
        for i, article in enumerate(top_articles, 1):
            lines.append(f"{i}. {article.title}")
            if article.excerpt:
                lines.append(f"   {article.excerpt[:100]}...")
            lines.append("")

        lines.append("--\nجريدة المغرب العربي الإلكترونية")
        body = "\n".join(lines)
        subject = "النشرة اليومية - المغرب العربي"

        subscribers = Newsletter.objects.filter(is_confirmed=True)
        enqueued = 0

        for subscriber in subscribers:
            EmailQueue.objects.create(
                recipient_email=subscriber.email,
                subject=subject,
                body=body,
            )
            enqueued += 1

        logger.info(f"Daily newsletter enqueued for {enqueued} subscribers")
        return {'enqueued': enqueued}
    except Exception as exc:
        logger.error(f"Daily newsletter failed: {exc}")
        raise self.retry(exc=exc)
