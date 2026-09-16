from .base import *

import dj_database_url
from urllib.parse import quote, unquote, urlparse, urlunparse


DEBUG = env_bool("DJANGO_DEBUG", True)
RATE_LIMIT_ENABLED = env_bool("RATE_LIMIT_ENABLED", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

RAILWAY_TCP_PROXY_DOMAIN = os.getenv("RAILWAY_TCP_PROXY_DOMAIN")
RAILWAY_TCP_PROXY_PORT = os.getenv("RAILWAY_TCP_PROXY_PORT")
if RAILWAY_TCP_PROXY_DOMAIN and RAILWAY_TCP_PROXY_PORT:
    private_database_url = os.getenv("DATABASE_URL", "")
    private_database = urlparse(private_database_url) if private_database_url else None
    railway_user = (
        os.getenv("PGUSER")
        or os.getenv("POSTGRES_USER")
        or (unquote(private_database.username) if private_database and private_database.username else None)
        or "postgres"
    )
    railway_password = (
        os.getenv("PGPASSWORD")
        or os.getenv("POSTGRES_PASSWORD")
        or (unquote(private_database.password) if private_database and private_database.password else "")
    )
    railway_database = (
        os.getenv("PGDATABASE")
        or os.getenv("POSTGRES_DB")
        or (private_database.path.lstrip("/") if private_database and private_database.path else None)
        or "railway"
    )
    RAILWAY_PUBLIC_DATABASE_URL = (
        f"postgresql://{quote(railway_user)}:{quote(railway_password)}@"
        f"{RAILWAY_TCP_PROXY_DOMAIN}:{RAILWAY_TCP_PROXY_PORT}/{quote(railway_database)}"
    )
else:
    RAILWAY_PUBLIC_DATABASE_URL = None

PRIVATE_RAILWAY_HOST = "postgres.railway.internal"
private_database_url = os.getenv("DATABASE_URL") or ""


def railway_public_url_with_private_credentials(public_url, private_url):
    public_database = urlparse(public_url or "")
    private_database = urlparse(private_url or "")
    if (
        PRIVATE_RAILWAY_HOST not in (private_database.hostname or "")
        or not public_database.hostname
        or ".rlwy.net" not in public_database.hostname
        or not private_database.username
        or private_database.password is None
    ):
        return public_url

    netloc = f"{quote(unquote(private_database.username))}:{quote(unquote(private_database.password))}@{public_database.hostname}"
    if public_database.port:
        netloc += f":{public_database.port}"
    path = public_database.path or private_database.path or "/railway"
    return urlunparse((public_database.scheme or "postgresql", netloc, path, "", public_database.query, ""))


configured_public_database_url = railway_public_url_with_private_credentials(
    os.getenv("DATABASE_PUBLIC_URL") or os.getenv("DATABASE_EXTERNAL_URL") or os.getenv("POSTGRES_PUBLIC_URL"),
    private_database_url,
)
configured_database_url = (
    RAILWAY_PUBLIC_DATABASE_URL
    or configured_public_database_url
    or private_database_url
    or os.getenv("POSTGRES_URL")
)

if not configured_database_url:
    raise RuntimeError("PostgreSQL DATABASE_URL is required. SQLite fallback is disabled for this project.")

if PRIVATE_RAILWAY_HOST in configured_database_url and not RAILWAY_PUBLIC_DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL points to postgres.railway.internal, which only works inside Railway. "
        "Set DATABASE_PUBLIC_URL/DATABASE_EXTERNAL_URL to a public Railway Postgres URL, or set "
        "RAILWAY_TCP_PROXY_DOMAIN and RAILWAY_TCP_PROXY_PORT so local Django can reach the production database."
    )

DATABASE_URL = configured_database_url
database_ssl_default = PRIVATE_RAILWAY_HOST not in DATABASE_URL
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=env_bool("DATABASE_SSL_REQUIRE", database_ssl_default),
    )
}
if USE_DJANGO_TENANTS:
    DATABASES["default"]["ENGINE"] = "django_tenants.postgresql_backend"

PRIVATE_RAILWAY_REDIS_HOST = "redis.railway.internal"
if PRIVATE_RAILWAY_REDIS_HOST in str(REDIS_URL or ""):
    REDIS_URL = "locmem://billing-saas-local"
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "billing-saas-local",
        }
    }
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
