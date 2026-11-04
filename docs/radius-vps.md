# Central RADIUS service

Expressnet uses one central RADIUS service for all tenants. A tenant only runs
the MikroTik provisioning command. They never enter a RADIUS address, secret,
or NAS configuration.

## What provisioning does automatically

1. The platform creates a unique shared secret for the router.
2. The provisioning script adds the MikroTik `/radius` client for Hotspot and
   PPPoE, using the platform RADIUS endpoint and that secret.
3. The router calls the provisioning callback after importing the script.
4. Expressnet records that router as a `RadiusNasClient` in the shared
   database, using the same secret.
5. The RADIUS container refreshes its NAS list and begins accepting the
   router's authentication and accounting packets.

## Deploy on an Ubuntu VPS

Use an Ubuntu VPS with a public IPv4 address. Allow **UDP 1812** and **UDP
1813** in both the VPS/cloud firewall and UFW. Do not expose the database or
Redis ports publicly for this purpose.

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
```

Clone this repository on the VPS, then create the private environment file:

```bash
cp .env.radius.example .env
nano .env
```

Set `DJANGO_SECRET_KEY` and `DATABASE_PUBLIC_URL` to the same production
values used by Expressnet. Set `RADIUS_SERVER_IP` to the VPS public IPv4.
Then run only the RADIUS service:

```bash
docker compose up -d --build radius
docker compose logs -f radius
```

## One platform setting in Railway

In the **Expressnet** Railway service, set the following once. These are
platform settings—not tenant settings:

```text
RADIUS_SERVER_IP=<VPS public IPv4 or DNS name>
RADIUS_AUTH_PORT=1812
RADIUS_ACCT_PORT=1813
```

Redeploy Expressnet after setting them. Each new provisioning command will
then create the MikroTik RADIUS client automatically. Re-run provisioning for
routers configured before the central service was available.

## Verify

On the VPS:

```bash
docker compose ps
docker compose logs --tail=100 radius
sudo ss -lunp | grep -E ':(1812|1813)'
```

The RADIUS log should report `Access-Request received` and `Access-Accept sent`
when a customer signs in. If a router is behind CGNAT shared with another
router, use the WireGuard hub as well so every router has a unique tunnel IP
for RADIUS authentication.
