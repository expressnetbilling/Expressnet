# Create Production Superuser From VS Code

Railway's `postgres.railway.internal` host only works inside Railway. From the VS Code terminal, use a public Railway Postgres connection URL or Railway TCP proxy.

## Option 1: Public database URL

1. In Railway, open the Postgres service.
2. Copy the public connection URL from the service variables or connection tab.
3. In PowerShell, set it for this terminal session:

```powershell
$env:DATABASE_PUBLIC_URL = "postgresql://USER:PASSWORD@PUBLIC_HOST:PORT/DB_NAME"
```

`DATABASE_EXTERNAL_URL` or `POSTGRES_PUBLIC_URL` also work if Railway uses one of those names. The host must not be `postgres.railway.internal`.

4. Create or update the production superuser:

```powershell
$env:DJANGO_SUPERUSER_EMAIL = "admin@example.com"
$env:DJANGO_SUPERUSER_PASSWORD = "change-this-password"
$env:DJANGO_SUPERUSER_NAME = "Super Admin"
.\venv\Scripts\python.exe manage.py ensure_superuser --settings=billing_saas_django.Settings.production
```

## Option 2: Railway TCP proxy

If Railway gives you a TCP proxy domain and port instead of a full public URL:

```powershell
$env:RAILWAY_TCP_PROXY_DOMAIN = "proxy.rlwy.net"
$env:RAILWAY_TCP_PROXY_PORT = "12345"
$env:DJANGO_SUPERUSER_EMAIL = "admin@example.com"
$env:DJANGO_SUPERUSER_PASSWORD = "change-this-password"
$env:DJANGO_SUPERUSER_NAME = "Super Admin"
.\venv\Scripts\python.exe manage.py ensure_superuser --settings=billing_saas_django.Settings.local
```

Keep `DATABASE_URL` pointed at Railway's internal URL for deployed Railway services. Use `DATABASE_PUBLIC_URL` or the TCP proxy only from your local terminal.
