from .base import *

DEBUG = env.bool('DEBUG', default=True)

# Database
# Default to SQLite in dev if PostgreSQL is not configured/running
DATABASES = {
    'default': env.db('DATABASE_URL', default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
}

# Development Local Cache
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-dev-cache',
    }
}
