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

Lets Railway reach a router's RouterOS API without a public IP on the router
and without inbound UDP on Railway. The router runs Tailscale as a subnet
router; a Railway service (`tailscale-bridge/`) joins the same tailnet in
userspace mode and forwards TCP ports over Railway private networking.

1. **Auth key.** Tailscale Admin Console, Settings, Keys, Generate auth key.
   Tick Reusable (and Tags or Ephemeral if you want). Use one key for the
   bridge and one per router, or a shared tagged key.
2. **Deploy the bridge.** Create a Railway service from this repo with root
   directory `tailscale-bridge`. Set `TS_AUTHKEY`, `TS_HOSTNAME` (default
   `railway-bridge`) and `PORT_FORWARDS` (`local_port:remote_ip:remote_port`,
   comma separated, e.g. `18728:172.17.0.1:8728`). Optionally mount a volume at
   `/var/lib/tailscale` to keep the node identity across deploys. No public
   domain is needed.
3. **Provision the router.** Edit the three values at the top of
   `tailscale-bridge/mikrotik-setup.rsc` (auth key, hostname, LAN subnet) and
   import it on a RouterOS v7 arm/arm64/x86 router with the `container`
   package (enable container mode first; the script header explains how).
   mipsbe/mmips routers need the LAN sidecar described at the end of the file.
4. **Approve routes.** Admin Console, Machines, the router, Edit route
   settings: tick `192.168.88.0/24` and `172.17.0.1/32`. Advertised routes do
   nothing until approved.
5. **Point the app at it.** For a tenant's router set `mikrotik_host` to
   `<bridge-service>.railway.internal` and `mikrotik_port` to the forwarded
   local port.

Limit: every router advertising the same `192.168.88.0/24` and `172.17.0.1/32`
overlaps in the tailnet, so only one router's routes can be active at a time.
For several routers use distinct LAN subnets per router, or forward to each
router's own tailnet IP (`100.x`) instead of its subnet.
