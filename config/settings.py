import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or (get_random_secret_key() if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY before running outside development.")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.buildings",
    "apps.murals",
    "apps.placements",
    "apps.users",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.getenv("POSTGRES_HOST"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "muralium"),
        "USER": os.getenv("POSTGRES_USER", "muralium"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{validator}"}
    for validator in [
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    ]
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "mine"
LOGOUT_REDIRECT_URL = "home"

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Saratov"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
# Images are served through access-checked views, with no MEDIA_URL route.
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MAP_TILE_URL = os.getenv("MAP_TILE_URL") or "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
GEOCODER_URL = os.getenv("GEOCODER_URL") or "https://photon.komoot.io/api/"
