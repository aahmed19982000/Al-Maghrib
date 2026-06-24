import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_email_queue(self):
    """
    Periodic task (runs every 60 seconds via Celery Beat).
    Processes pending emails from the EmailQueue model in batches.
    Sends each email via Django's mail system and updates status.
    """
    try:
        from django.utils import timezone
        from django.core.mail import send_mail
        from django.conf import settings
        from notifications.models import EmailQueue

        # Fetch pending emails in batch (max 50 per cycle)
        pending_emails = EmailQueue.objects.filter(
            status='pending'
        ).order_by('created_at')[:50]

        if not pending_emails.exists():
            return {'processed': 0, 'status': 'no_pending_emails'}

        sent_count = 0
        failed_count = 0

        for email_entry in pending_emails:
            try:
                send_mail(
                    subject=email_entry.subject,
                    message=email_entry.body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email_entry.recipient_email],
                    fail_silently=False,
                )
                email_entry.status = 'sent'
                email_entry.sent_at = timezone.now()
                email_entry.attempts += 1
                email_entry.save(update_fields=['status', 'sent_at', 'attempts'])
                sent_count += 1
            except Exception as mail_exc:
                email_entry.attempts += 1
                if email_entry.attempts >= 3:
                    email_entry.status = 'failed'
                email_entry.save(update_fields=['status', 'attempts'])
                failed_count += 1
                logger.warning(
                    f"Failed to send email to {email_entry.recipient_email}: {mail_exc}"
                )

        logger.info(
            f"Email queue processed: {sent_count} sent, {failed_count} failed"
        )
        return {'sent': sent_count, 'failed': failed_count}
    except Exception as exc:
        logger.error(f"Email queue processing failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2)
def send_notification_task(self, user_id, verb, description=None):
    """
    Create a notification record asynchronously.
    This offloads notification creation from the request/response cycle.
    """
    try:
        from django.contrib.auth.models import User
        from notifications.models import Notification

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logger.warning(f"User {user_id} not found for notification")
            return {'status': 'user_not_found'}

        notification = Notification.objects.create(
            user=user,
            verb=verb,
            description=description or '',
        )
        logger.info(f"Notification created for user {user_id}: {verb}")
        return {'notification_id': notification.pk}
    except Exception as exc:
        logger.error(f"Notification creation failed for user {user_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2)
def send_contact_email_task(self, name, email, subject, message):
    """
    Send contact form email asynchronously via Celery.
    """
    try:
        from django.core.mail import send_mail
        from django.conf import settings

        email_body = (
            f"الاسم: {name}\n"
            f"البريد الإلكتروني: {email}\n"
            f"الموضوع: {subject}\n\n"
            f"الرسالة:\n{message}"
        )

        send_mail(
            subject=f"[اتصل بنا] {subject}",
            message=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.CONTACT_EMAIL],
            fail_silently=False,
        )
        logger.info(f"Contact email sent from {email}")
        return {'status': 'sent'}
    except Exception as exc:
        logger.error(f"Contact email failed: {exc}")
        raise self.retry(exc=exc)
