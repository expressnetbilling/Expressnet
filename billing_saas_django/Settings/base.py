from pathlib import Path
import importlib.util
import os
from urllib.parse import quote, urlparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_path(name, default):
    value = os.getenv(name, default).strip().strip("/")
    return value or default.strip("/")


def unique_apps(apps):
    return list(dict.fromkeys(apps))


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or "dev-only-change-me"
API_BASE_PATH = env_path("API_BASE_PATH", "api")
ADMIN_API_PATH = env_path("ADMIN_API_PATH", "admin")
ADMIN_FRONTEND_PATH = env_path("ADMIN_FRONTEND_PATH", "admin")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_CURRENCY = os.getenv("PAYSTACK_CURRENCY", "KES")
PAYSTACK_CALLBACK_BASE_URL = os.getenv("PAYSTACK_CALLBACK_BASE_URL", os.getenv("PUBLIC_APP_URL", ""))

USE_DJANGO_TENANTS = env_bool("USE_DJANGO_TENANTS", False)
PUBLIC_BASE_DOMAIN = os.getenv("PUBLIC_BASE_DOMAIN", "expressnetbilling.com").strip().lower()
TENANT_BASE_DOMAIN = os.getenv("TENANT_BASE_DOMAIN", PUBLIC_BASE_DOMAIN).strip().lower()
APP_SUBDOMAIN = os.getenv("APP_SUBDOMAIN", "app").strip().lower()
ADMIN_SUBDOMAIN = os.getenv("ADMIN_SUBDOMAIN", "admin").strip().lower()
ADMIN_API_ALLOWED_HOSTS = env_list("ADMIN_API_ALLOWED_HOSTS")
for admin_api_host in (
    PUBLIC_BASE_DOMAIN,
    f"www.{PUBLIC_BASE_DOMAIN}" if PUBLIC_BASE_DOMAIN else "",
    f"{APP_SUBDOMAIN}.{PUBLIC_BASE_DOMAIN}" if APP_SUBDOMAIN and PUBLIC_BASE_DOMAIN else "",
    f"{ADMIN_SUBDOMAIN}.{PUBLIC_BASE_DOMAIN}" if ADMIN_SUBDOMAIN and PUBLIC_BASE_DOMAIN else "",
    os.getenv("RAILWAY_PUBLIC_DOMAIN", ""),
    os.getenv("RAILWAY_STATIC_URL", ""),
):
    if admin_api_host:
        parsed_admin_api_host = urlparse(
            admin_api_host if "://" in admin_api_host else f"//{admin_api_host}"
        ).hostname
        if parsed_admin_api_host:
            ADMIN_API_ALLOWED_HOSTS.append(parsed_admin_api_host.lower())
ADMIN_API_ALLOWED_HOSTS = list(dict.fromkeys(ADMIN_API_ALLOWED_HOSTS))
API_MAX_BODY_BYTES = int(os.getenv("API_MAX_BODY_BYTES", str(2 * 1024 * 1024)))
API_GATEWAY_RATE_LIMIT = int(os.getenv("API_GATEWAY_RATE_LIMIT", "300"))
API_GATEWAY_RATE_WINDOW = int(os.getenv("API_GATEWAY_RATE_WINDOW", "60"))
SESSION_IDLE_TIMEOUT_SECONDS = int(os.getenv("SESSION_IDLE_TIMEOUT_SECONDS", "600"))
TENANT_AUTH_CACHE_SECONDS = int(os.getenv("TENANT_AUTH_CACHE_SECONDS", "5"))
ROUTER_STATUS_CACHE_SECONDS = int(os.getenv("ROUTER_STATUS_CACHE_SECONDS", "4"))
ROUTER_AGENT_HEARTBEAT_SECONDS = int(os.getenv("ROUTER_AGENT_HEARTBEAT_SECONDS", "60"))
TENANT_EMAIL_VERIFICATION_REQUIRED = env_bool("TENANT_EMAIL_VERIFICATION_REQUIRED", False)

SHARED_APPS = [
    "daphne",
    "channels",
    "django_tenants",
    "core",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
]

TENANT_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "network",
    "management",
]

LEGACY_APPS = [
    "billing_api",
]

INSTALLED_APPS = (
    unique_apps([*SHARED_APPS, *TENANT_APPS, *LEGACY_APPS])
    if USE_DJANGO_TENANTS
    else unique_apps(app for app in [*SHARED_APPS, *TENANT_APPS, *LEGACY_APPS] if app != "django_tenants")
)

TENANT_MODEL = "core.Tenant"
TENANT_DOMAIN_MODEL = "core.Domain"
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",) if USE_DJANGO_TENANTS else []

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
]
if importlib.util.find_spec("whitenoise"):
    MIDDLEWARE.append("whitenoise.middleware.WhiteNoiseMiddleware")
if USE_DJANGO_TENANTS:
    MIDDLEWARE.append("django_tenants.middleware.main.TenantMainMiddleware")
MIDDLEWARE += [
    "billing_api.middleware.ApiGatewayMiddleware",
    "billing_api.middleware.SecurityHeadersMiddleware",
    "billing_api.middleware.SimpleRateLimitMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "billing_saas_django.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "frontend" / "dist"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]
WSGI_APPLICATION = "billing_saas_django.wsgi.application"
ASGI_APPLICATION = "billing_saas_django.asgi.application"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/assets/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist" / "assets"]
if importlib.util.find_spec("whitenoise"):
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "billing_api.User"

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER or "no-reply@billing-saas.local"
ADMIN_NOTIFICATION_EMAILS = env_list("ADMIN_NOTIFICATION_EMAILS")
TENANT_LOGIN_2FA_ENABLED = env_bool("TENANT_LOGIN_2FA_ENABLED", False)

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
}

def railway_redis_url():
    host = os.getenv("REDISHOST")
    port = os.getenv("REDISPORT", "6379")
    if not host or "${{" in host or "}" in host or "${{" in port or "}" in port:
        return None
    user = os.getenv("REDISUSER", "default")
    password = os.getenv("REDISPASSWORD") or os.getenv("REDIS_PASSWORD") or ""
    return f"redis://{quote(user)}:{quote(password)}@{host}:{port}/0"


def usable_redis_url(value):
    if not value or "${{" in value or "}" in value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        return None
    return value


REDIS_URL = usable_redis_url(os.getenv("REDIS_PUBLIC_URL")) or usable_redis_url(os.getenv("REDIS_URL")) or railway_redis_url() or "redis://localhost:6379/0"
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            # Status events are edge notifications; durable state remains in
            # PostgreSQL. A short expiry prevents stale router events building
            # up while a browser is disconnected.
            "expiry": 30,
            "capacity": 100,
        },
    },
}
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache"
        if importlib.util.find_spec("django_redis")
        else "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": REDIS_URL if importlib.util.find_spec("django_redis") else "billing-saas-local",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"}
        if importlib.util.find_spec("django_redis")
        else {},
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_PUBLISH_RETRY = False
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BEAT_SCHEDULE = {
    "expire-tenant-subscriptions-hourly": {
        "task": "billing_api.tasks.expire_tenant_subscriptions",
        "schedule": 3600.0,
    },
    "expire-customer-access-every-five-minutes": {
        "task": "billing_api.tasks.expire_customer_access",
        "schedule": 300.0,
    },
    "generate-expired-customer-invoices-every-ten-minutes": {
        "task": "billing_api.tasks.generate_expired_customer_invoices",
        "schedule": 600.0,
    },
    "notify-router-offline-every-five-minutes": {
        "task": "billing_api.tasks.notify_router_offline",
        "schedule": 300.0,
    },
    "reconcile-pending-payment-work-every-minute": {
        "task": "billing_api.tasks.reconcile_pending_payment_work",
        "schedule": 60.0,
    },
}
