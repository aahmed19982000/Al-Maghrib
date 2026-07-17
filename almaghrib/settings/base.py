from pathlib import Path
import environ

# Initialize environment variables helper
env = environ.Env()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# Since this file is in almaghrib/settings/base.py, we need 3 .parent calls to get to the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Read .env file if it exists
environ.Env.read_env(BASE_DIR / '.env')

# Quick-start development settings - unsuitable for production
SECRET_KEY = env('SECRET_KEY', default='django-insecure-default-key-for-dev')

# Key used to encrypt sensitive fields at rest (Gemini API key, Telegram bot
# token, WordPress application passwords). Insecure fixed fallback for local
# dev only — production MUST set FIELD_ENCRYPTION_KEY in .env (see prod.py).
# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY = env('FIELD_ENCRYPTION_KEY', default='5q3zduDPj233xFGBU_U5zY41OsqhA-kGOEgnb3PAwTg=')

ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'modeltranslation', # Must be before admin
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps', # Django Sitemaps framework
    # Third-Party Apps
    'mptt',
    'rest_framework',
    'taggit',
    'sorl.thumbnail',
    'django_ckeditor_5',
    'guardian',
    'compressor',
    'django_celery_beat',
    # Local Apps
    'core',
    'news',
    'accounts',
    'dashboard',
    'api',
    'notifications',
]

MIDDLEWARE = [
    'core.middleware.SubdomainRoutingMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # Whitenoise Middleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware', # Locale Middleware for language detection
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'almaghrib.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'news.context_processors.global_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'almaghrib.wsgi.application'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'ar'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# Translation Languages
LANGUAGES = [
    ('ar', 'عربي'),
    ('en', 'English'),
]

MODELTRANSLATION_DEFAULT_LANGUAGE = 'ar'
MODELTRANSLATION_LANGUAGES = ('ar', 'en')

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Celery Configurations
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Run tasks synchronously in dev when Redis is unavailable
CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=True)
CELERY_TASK_EAGER_PROPAGATES = True

# Celery Beat Scheduler
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Celery Beat periodic task schedules
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'process-email-queue-every-minute': {
        'task': 'notifications.tasks.process_email_queue',
        'schedule': 60.0,  # every 60 seconds
    },
    'cleanup-expired-records-daily': {
        'task': 'core.tasks.cleanup_expired_and_deleted_records',
        'schedule': crontab(hour=3, minute=0),  # daily at 3:00 AM
    },
    'send-daily-newsletter': {
        'task': 'core.tasks.send_daily_newsletter',
        'schedule': crontab(hour=8, minute=0),  # daily at 8:00 AM
    },
    'scrape-and-generate-news-every-4-hours': {
        'task': 'news.tasks.scrape_and_generate_news_task',
        # Kept the original entry name so django-celery-beat's DatabaseScheduler
        # updates this same DB row in place instead of leaving the old 4-hour
        # entry orphaned in production. Runs every 10 minutes now so per-site
        # schedule slots (WordPressScheduleSlot) can fire close to their
        # configured Cairo-local time; sites with no slots configured are
        # unaffected and still only publish per their own daily_limit/articles_per_run.
        'schedule': crontab(minute='*/10'),
    },
}

# Email Backend Configuration
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@almaghrib.com')
CONTACT_EMAIL = env('CONTACT_EMAIL', default='contact@almaghrib.com')

# CKEditor 5 Configurations
CKEDITOR_5_CONFIGS = {
    'default': {
        'language': 'ar',
        'toolbar': ['heading', '|', 'bold', 'italic', 'link', 'bulletedList', 'numberedList', 'blockQuote', 'imageUpload', 'alignment'],
    },
    'extends': {
        'language': 'ar',
        'blockToolbar': [
            'paragraph', 'heading1', 'heading2', 'heading3',
            '|',
            'bulletedList', 'numberedList',
            '|',
            'blockQuote',
        ],
        'toolbar': [
            'heading', '|', 'outdent', 'indent', '|', 'bold', 'italic', 'underline', 'strikethrough', 'link',
            'alignment', '|', 'bulletedList', 'numberedList', 'todoList', '|',
            'blockQuote', 'imageUpload', 'insertTable', 'mediaEmbed', '|',
            'fontSize', 'fontFamily', 'fontColor', 'fontBackgroundColor', '|',
            'removeFormat', 'sourceEditing'
        ],
        'image': {
            'toolbar': ['imageTextAlternative', '|', 'imageStyle:alignLeft',
                        'imageStyle:alignRight', 'imageStyle:alignCenter', 'imageStyle:side',  '|'],
            'styles': [
                'full',
                'side',
                'alignLeft',
                'alignRight',
                'alignCenter',
            ]
        },
        'table': {
            'contentToolbar': [ 'tableColumn', 'tableRow', 'mergeTableCells',
            'tableProperties', 'tableCellProperties' ]
        },
        'header': {
            'options': [
                {'model': 'paragraph', 'title': 'Paragraph', 'class': 'ck-heading_paragraph'},
                {'model': 'heading1', 'view': 'h1', 'title': 'Heading 1', 'class': 'ck-heading_heading1'},
                {'model': 'heading2', 'view': 'h2', 'title': 'Heading 2', 'class': 'ck-heading_heading2'},
                {'model': 'heading3', 'view': 'h3', 'title': 'Heading 3', 'class': 'ck-heading_heading3'}
            ]
        }
    },
    'extends_en': {
        'language': 'en',
        'blockToolbar': [
            'paragraph', 'heading1', 'heading2', 'heading3',
            '|',
            'bulletedList', 'numberedList',
            '|',
            'blockQuote',
        ],
        'toolbar': [
            'heading', '|', 'outdent', 'indent', '|', 'bold', 'italic', 'underline', 'strikethrough', 'link',
            'alignment', '|', 'bulletedList', 'numberedList', 'todoList', '|',
            'blockQuote', 'imageUpload', 'insertTable', 'mediaEmbed', '|',
            'fontSize', 'fontFamily', 'fontColor', 'fontBackgroundColor', '|',
            'removeFormat', 'sourceEditing'
        ],
        'image': {
            'toolbar': ['imageTextAlternative', '|', 'imageStyle:alignLeft',
                        'imageStyle:alignRight', 'imageStyle:alignCenter', 'imageStyle:side',  '|'],
            'styles': [
                'full',
                'side',
                'alignLeft',
                'alignRight',
                'alignCenter',
            ]
        },
        'table': {
            'contentToolbar': [ 'tableColumn', 'tableRow', 'mergeTableCells',
            'tableProperties', 'tableCellProperties' ]
        },
        'header': {
            'options': [
                {'model': 'paragraph', 'title': 'Paragraph', 'class': 'ck-heading_paragraph'},
                {'model': 'heading1', 'view': 'h1', 'title': 'Heading 1', 'class': 'ck-heading_heading1'},
                {'model': 'heading2', 'view': 'h2', 'title': 'Heading 2', 'class': 'ck-heading_heading2'},
                {'model': 'heading3', 'view': 'h3', 'title': 'Heading 3', 'class': 'ck-heading_heading3'}
            ]
        }
    }
}
CKEDITOR_5_FILE_UPLOAD_PERMISSION = "staff"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'guardian.backends.ObjectPermissionBackend',
)

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
]

COMPRESS_ENABLED = True

# Caching Strategy: Redis Cache Backend
CACHES = {
    'default': {
        'BACKEND': 'django.core.caches.backends.redis.RedisCache',
        'LOCATION': env('REDIS_CACHE_URL', default='redis://127.0.0.1:6379/1'),
    }
}

# Media Optimization: S3/DigitalOcean Spaces for Production
USE_SPACES = env.bool('USE_SPACES', default=False)
if USE_SPACES:
    AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = env('AWS_S3_ENDPOINT_URL', default='https://ams3.digitaloceanspaces.com')
    AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}
    AWS_DEFAULT_ACL = 'public-read'
    AWS_QUERYSTRING_AUTH = False
    
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# sorl-thumbnail configurations
THUMBNAIL_FORMAT = 'WEBP'
THUMBNAIL_QUALITY = 85


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'api.auth.APITokenAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ),
}
