import time
import logging
import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.models import User
from news.models import AISettings, AIImportLog
from news.ai_utils import run_ai_generation_cycle

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Runs a polling Telegram bot to trigger AI news generation and get daily reports'

    def handle(self, *args, **options):
        ai_settings = AISettings.get_settings()
        bot_token = ai_settings.telegram_bot_token

        if not bot_token:
            self.stdout.write(self.style.WARNING("Telegram Bot Token is not configured in settings. Exiting."))
            return

        self.stdout.write(self.style.SUCCESS(f"Starting Telegram Bot polling..."))
        
        offset = 0
        base_url = f"https://api.telegram.org/bot{bot_token}"

        while True:
            try:
                # Reload settings inside the loop to capture dynamic token changes
                ai_settings = AISettings.get_settings()
                if ai_settings.telegram_bot_token != bot_token:
                    bot_token = ai_settings.telegram_bot_token
                    base_url = f"https://api.telegram.org/bot{bot_token}"
                    self.stdout.write(self.style.SUCCESS("Telegram Bot Token updated. Re-initializing..."))

                if not bot_token:
                    self.stdout.write(self.style.WARNING("Telegram Bot Token cleared. Pausing..."))
                    time.sleep(10)
                    continue

                url = f"{base_url}/getUpdates"
                params = {'offset': offset, 'timeout': 20}
                res = requests.get(url, params=params, timeout=25)
                
                if res.status_code != 200:
                    time.sleep(5)
                    continue

                updates = res.json().get('result', [])
                for update in updates:
                    offset = update['update_id'] + 1
                    message = update.get('message')
                    if not message:
                        continue
                    
                    chat = message.get('chat', {})
                    chat_id = chat.get('id')
                    text = message.get('text', '').strip()
                    user_info = message.get('from', {})
                    first_name = user_info.get('first_name', '')

                    if not text:
                        continue

                    # Check authorization
                    allowed_chats_str = ai_settings.telegram_allowed_chats or ""
                    allowed_ids = [cid.strip() for cid in allowed_chats_str.split(',') if cid.strip()]
                    
                    is_authorized = True
                    if allowed_ids:
                        is_authorized = str(chat_id) in allowed_ids

                    if not is_authorized:
                        # Reply with unauthorized message
                        self.send_message(base_url, chat_id, f"🚫 عذراً {first_name}، أنت غير مصرح لك بالتحكم في هذا البوت.\nمعرف الدردشة الخاص بك (Chat ID) هو: `{chat_id}`.\nيرجى إضافته في لوحة تحكم Django للسماح لك.")
                        continue

                    # Process commands
                    if text == '/start':
                        msg = (
                            f"🤖 أهلاً بك يا {first_name} في بوت إدارة محرّر الذكاء الاصطناعي (AI News Bot)!\n\n"
                            f"الأوامر المتاحة:\n"
                            f"◀️ /run - بدء عملية جلب الأخبار وتوليدها فوراً.\n"
                            f"◀️ /report - الحصول على تقرير بما تم نشره اليوم.\n"
                            f"◀️ /id - الحصول على معرف الدردشة الخاص بك (Chat ID)."
                        )
                        self.send_message(base_url, chat_id, msg)

                    elif text == '/id':
                        self.send_message(base_url, chat_id, f"🆔 معرف الدردشة الخاص بك هو:\n`{chat_id}`")

                    elif text == '/run':
                        self.send_message(base_url, chat_id, "⏳ جاري البدء في دورة جلب وتوليد الأخبار بالذكاء الاصطناعي... يرجى الانتظار (قد يستغرق ذلك دقيقة أو دقيقتين).")
                        
                        start_time = timezone.now()
                        try:
                            count = run_ai_generation_cycle()
                            
                            # Fetch newly created success logs
                            new_logs = AIImportLog.objects.filter(created_at__gte=start_time, status='success')
                            
                            if count > 0:
                                reply = f"✅ اكتملت الدورة بنجاح! تم توليد ونشر {count} خبر جديد:\n\n"
                                for idx, log in enumerate(new_logs, 1):
                                    site_prefix = f"[{log.wp_site.name}] " if log.wp_site else "[الموقع المحلي] "
                                    title_text = log.title or (log.article.title if log.article else "خبر جديد")
                                    link = log.published_url or (log.article.get_absolute_url() if log.article else "")
                                    reply += f"{idx}. {site_prefix}*{title_text}*\n🔗 {link}\n\n"
                            else:
                                reply = "ℹ️ اكتملت الدورة بنجاح. لم يتم العثور على أخبار جديدة (غير مكررة) للنشر في هذا الوقت."
                                
                            self.send_message(base_url, chat_id, reply)
                        except Exception as ex:
                            self.send_message(base_url, chat_id, f"❌ فشلت الدورة بسبب خطأ في الخادم:\n`{str(ex)}`")

                    elif text == '/report':
                        today = timezone.now().date()
                        logs = AIImportLog.objects.filter(created_at__date=today)
                        
                        success_logs = logs.filter(status='success')
                        failed_logs = logs.filter(status='failed')
                        
                        report = f"📊 *تقرير النشر اليومي ({today.strftime('%Y-%m-%d')}):*\n\n"
                        report += f"✅ عدد الأخبار المنشورة بنجاح: {success_logs.count()}\n"
                        report += f"❌ عدد العمليات الفاشلة: {failed_logs.count()}\n\n"
                        
                        if success_logs.exists():
                            report += "📝 *الأخبار المنشورة:*\n"
                            for idx, log in enumerate(success_logs, 1):
                                site_prefix = f"[{log.wp_site.name}] " if log.wp_site else "[الموقع المحلي] "
                                title_text = log.title or (log.article.title if log.article else "خبر")
                                link = log.published_url or (log.article.get_absolute_url() if log.article else "")
                                report += f"{idx}. {site_prefix}*{title_text}*\n🔗 {link}\n"
                            report += "\n"
                                
                        if failed_logs.exists():
                            report += "⚠️ *العمليات الفاشلة:*\n"
                            for idx, log in enumerate(failed_logs, 1):
                                site_prefix = f"[{log.wp_site.name}] " if log.wp_site else ""
                                report += f"{idx}. {site_prefix} الخبر: {log.title or 'بدون عنوان'}\nالخطأ: `{log.error_message}`\n"
                                
                        self.send_message(base_url, chat_id, report)

            except Exception as e:
                logger.error(f"Error in Telegram Bot Polling: {e}")
                time.sleep(5)

    def send_message(self, base_url, chat_id, text):
        try:
            url = f"{base_url}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'Markdown'
            }
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
