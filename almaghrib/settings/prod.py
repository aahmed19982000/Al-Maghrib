from .base import *

DEBUG = False

# Production Database (Requires PostgreSQL)
DATABASES = {
    'default': env.db('DATABASE_URL')
}

# Production Redis Cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://127.0.0.1:6379/0"),
    }
}

# Production Security Headers
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False) # Off by default in dev/test, set to True in actual prod
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Enable offline compression for faster page rendering
COMPRESS_OFFLINE = True

