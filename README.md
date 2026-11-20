# Expressnet v5

Modular Django monolith for ISP billing, network provisioning, RADIUS, MikroTik,
Paystack, and M-Pesa flows.

## Run Locally

```powershell
.\venv\Scripts\Activate.ps1
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```

`makemigrations` is plural. A compatibility alias named `makemigration` is also
available for the common typo.

## Tenant Mode

Local SQLite mode is the default for development. PostgreSQL is required for
schema-per-tenant mode:

```powershell
$env:USE_DJANGO_TENANTS = "true"
$env:DATABASE_URL = "postgresql://user:password@host:5432/dbname"
python manage.py migrate_schemas --shared
python manage.py migrate_schemas --tenant
```

See [docs/tenant_runbook.md](docs/tenant_runbook.md) for onboarding, local
subdomain testing, and per-tenant backup/restore commands.

## Central RADIUS

The RADIUS server is a Docker service in the same Compose deployment as
Expressnet. It serves mutually authenticated RadSec over TCP 2083 and creates
its persistent PKI automatically; router provisioning imports the required CA
and client certificate without tenant input. See
[docs/radsec-vps.md](docs/radsec-vps.md).

## Tailscale bridge for MikroTik routers

Lets Railway reach a router's RouterOS API with no public IP on the router and
no inbound UDP on Railway. Each router joins the tailnet as an endpoint with
its own `100.x.y.z` address; no subnet routes are advertised, so routers can
all share `192.168.88.0/24` locally. A Railway service (`tailscale-bridge/`)
joins the same tailnet in userspace mode and exposes a SOCKS5 proxy, and the
web app dials each router through it.

1. **Auth key.** Tailscale Admin Console, Settings, Keys, Generate auth key.
   Tick Reusable (and Tags or Ephemeral if you want). Use one key for the
   bridge and one for routers, or a shared tagged key. In Access Controls,
   allow the bridge's tag or user to reach the routers on tcp 22, 443, 8728
   and 8729.
2. **Deploy the bridge.** Create a Railway service from this repo with root
   directory `tailscale-bridge`. Set `TS_AUTHKEY` and `TS_HOSTNAME` (default
   `railway-bridge`). Optionally mount a volume at `/var/lib/tailscale`. No
   public domain is needed. It listens on 1055 (SOCKS5) and 1056 (HTTP proxy).
3. **Point the app at it.** On the web and worker services set
   `TAILSCALE_SOCKS5_PROXY=<bridge-service>.railway.internal:1055`.
4. **Provision each router.** Edit the values at the top of
   `tailscale-bridge/mikrotik-setup.rsc` (auth key, hostname `router-<id>`,
   optional callback URL) and import it on a RouterOS v7 arm/arm64/x86 router
   with the `container` package (the script header explains enabling it).
   Inside the container, `tailscale serve` forwards ports 22, 443, 8728 and
   8729 to the router at `172.17.0.1`. mipsbe/mmips routers need the LAN
   sidecar described at the end of the file.
5. **Record the router's name.** The tenant field `mikrotik_tailscale_host`
   (set by the script's callback, or in the router settings API) holds the
   router's tailnet IP or name. When it is set and `TAILSCALE_SOCKS5_PROXY` is
   configured, RouterOS API calls go through the bridge to that host;
   otherwise the previous `mikrotik_host` behaviour is unchanged.

Only the RouterOS API uses the proxy today; REST and SSH are forwarded on the
router but the app does not call them yet.
