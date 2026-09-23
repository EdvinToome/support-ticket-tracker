import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

DATABASES = {"default": dj_database_url.parse(os.environ["TEST_DATABASE_URL"])}
if DATABASES["default"]["HOST"] not in {"127.0.0.1", "localhost", "postgres"}:
    raise ImproperlyConfigured("Tests require an isolated local or CI PostgreSQL server.")
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
OPENAI_API_KEY = ""
