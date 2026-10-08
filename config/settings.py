"""
Omnipax backend settings (Django + DRF + Channels + Celery).

Postgres is the deploy target (pxxl). Locally, if none of the POSTGRES_*
env vars are set, SQLite is used so the project boots without a local
Postgres server. Redis is expected at REDIS_URL (local default
redis://127.0.0.1:6379/0) for the Channels layer and the Celery broker.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

# --- CORS ---
# Auth is Bearer JWT in a header (no cookies/credentials), so the browser
# sends nothing sensitive on cross-origin requests and any origin may call the
# API — Vercel prod + preview URLs included without maintenance.
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = False

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "channels",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "django_celery_beat",
    "drf_spectacular",
    # omnipax apps
    "accounts",
    "geo",
    "rides",
    "drivers",
    "payments",
    "realtime",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.User"

# Database: Postgres when POSTGRES_DB is set, else local SQLite.
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF + JWT ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Omnipax API",
    "DESCRIPTION": "Omnipax ride-hailing backend — passengers, drivers, pins, payments.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SECURITY": [{"BearerAuth": []}],
    "COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
}

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# --- Channels ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    },
}

# --- Celery ---
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE

# --- Email (OTP delivery) ---
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp-relay.brevo.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
# Cap the SMTP handshake so a blocked/mute mail server can never hang a
# gunicorn sync worker long enough to trip WORKER TIMEOUT.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "15"))
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@omnipax.local")

# --- Bachs (tip payments; sandbox stub unless BACHS_API_URL is set) ---
BACHS_API_URL = os.environ.get("BACHS_API_URL", "")
BACHS_SECRET_KEY = os.environ.get("BACHS_SECRET_KEY", "")
BACHS_WEBHOOK_SECRET = os.environ.get("BACHS_WEBHOOK_SECRET", "")
BACHS_CALLBACK_URL = os.environ.get("BACHS_CALLBACK_URL", "")

# --- Omnipax tunables (design spec §8b) ---
PIN_TTL_MINUTES = int(os.environ.get("PIN_TTL_MINUTES", "6"))
MAX_JUNCTION_RADIUS_METERS = int(os.environ.get("MAX_JUNCTION_RADIUS_METERS", "300"))
DRIVER_LOCATION_STALE_SECONDS = int(os.environ.get("DRIVER_LOCATION_STALE_SECONDS", "120"))
STANDARD_VISIBILITY_COUNT = int(os.environ.get("STANDARD_VISIBILITY_COUNT", "3"))
EMERGENCY_ACCEPT_SECONDS = int(os.environ.get("EMERGENCY_ACCEPT_SECONDS", "90"))
ZONE_SCORE_PROXIMITY_METERS = int(os.environ.get("ZONE_SCORE_PROXIMITY_METERS", "2000"))
OTP_REQUEST_LIMIT = int(os.environ.get("OTP_REQUEST_LIMIT", "3"))
OTP_REQUEST_WINDOW_SECONDS = int(os.environ.get("OTP_REQUEST_WINDOW_SECONDS", "900"))
OTP_VERIFY_ATTEMPTS = int(os.environ.get("OTP_VERIFY_ATTEMPTS", "5"))
PICKUP_CODE_ATTEMPTS = int(os.environ.get("PICKUP_CODE_ATTEMPTS", "5"))
PIN_EXPIRY_SWEEP_SECONDS = int(os.environ.get("PIN_EXPIRY_SWEEP_SECONDS", "45"))

# Rough Akwa Ibom bounding box sanity check for coordinate inputs
# (lat, lng) min/max.
AKWA_IBOM_BBOX = {
    "min_lat": 4.2,
    "max_lat": 5.6,
    "min_lng": 7.4,
    "max_lng": 8.5,
}

# --- Celery Beat ---
CELERY_BEAT_SCHEDULE = {
    "expire-pins": {
        "task": "rides.tasks.expire_pins",
        "schedule": float(PIN_EXPIRY_SWEEP_SECONDS),
    },
}
