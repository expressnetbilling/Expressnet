# Expressnet v5 Tenant Runbook

This is the first operational runway for the modular monolith migration. The
legacy `billing_api` app remains installed while models are moved in staged data
migrations.

## Enable tenant mode

Set these environment variables on a PostgreSQL-backed environment:

```bash
USE_DJANGO_TENANTS=true
TENANT_BASE_DOMAIN=expressnetbilling.com
DATABASE_URL=postgresql://...
```

SQLite cannot run schema-per-tenant mode.

For production tenant login URLs such as `citynet.expressnetbilling.com`, point
the base domain and wildcard (`*.expressnetbilling.com`) DNS records at the web
application and configure wildcard TLS coverage on the hosting platform. Set
`PUBLIC_BASE_DOMAIN` and `TENANT_BASE_DOMAIN` to `expressnetbilling.com` in the
production environment. Production settings fall back to `PUBLIC_BASE_DOMAIN`
if `TENANT_BASE_DOMAIN` is missing or set to a local host.

MikroTik provisioning uses `PUBLIC_APP_URL` for the captive-portal URL by
default. This is deliberately safe on Railway: a DNS CNAME without a matching
Railway custom-domain route causes the customer redirect to time out. After
wildcard DNS, TLS, and the hosting route are live, set
`CAPTIVE_PORTAL_TENANT_SUBDOMAINS_ENABLED=true` to provision a router for
`citynet` with `https://citynet.expressnetbilling.com/api/captive/<tenant-id>`.

## Migrate schemas

```bash
python manage.py migrate_schemas --shared
python manage.py migrate_schemas --tenant
```

Use `migrate` only for the legacy/local single-schema path. In tenant mode,
`migrate_schemas` is the deployment command.

## Onboard an ISP

```bash
python manage.py create_isp_tenant \
  --business-name "Demo ISP" \
  --email owner@example.com \
  --slug demo
```

This creates:

- `core.Tenant` in the public schema
- an `isp_demo` PostgreSQL schema
- a primary `demo.expressnet.app` domain

## Local subdomain testing

Add a hosts entry:

```text
127.0.0.1 demo.localhost
```

Create the tenant with `--domain demo.localhost`, then browse using that host so
`TenantMainMiddleware` can resolve the schema from the `Host` header.

## Backup and restore

Back up one tenant schema:

```bash
pg_dump "$DATABASE_URL" --schema=isp_demo --format=custom --file=isp_demo.dump
```

Restore one tenant schema into a staging database first, then production only
after validating row counts and application smoke tests:

```bash
pg_restore --dbname "$DATABASE_URL" --schema=isp_demo --clean isp_demo.dump
```

Do not drop tenant schemas automatically; `core.Tenant.auto_drop_schema` is
disabled intentionally.
