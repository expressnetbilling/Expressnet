# RadSec gateway for MikroTik PPPoE and Hotspot

Use this deployment when the billing application is on Railway and routers
cannot send UDP RADIUS packets to it. The gateway listens on a public VPS over
TCP 2083 with TLS; the Python RADIUS policy service stays on the same VPS and
uses UDP only on loopback.

```text
MikroTik -- mutual TLS / TCP 2083 --> VPS FreeRADIUS --> 127.0.0.1 UDP --> Django AAA --> Railway PostgreSQL
```

Do not point a MikroTik directly at a Railway TCP proxy. RouterOS native
RadSec always uses TCP 2083, while Railway assigns a different public proxy
port. Use a VPS with a fixed public IPv4 and allow only TCP 2083 in its cloud
firewall and UFW.

## VPS deployment

On the VPS, clone this repository and create `secrets/radsec/`. Never commit
this directory. Set `DATABASE_PUBLIC_URL` to the resolved Railway PostgreSQL
TCP-proxy URL, plus the normal `DJANGO_SECRET_KEY` and application variables
in `.env`.

```bash
mkdir -p secrets/radsec
cp .env.example .env
nano .env
docker compose build radsec
docker compose up -d radsec
docker compose logs -f radsec
```

The service will not start until these files exist:

```text
secrets/radsec/server.pem
secrets/radsec/server-key.pem
secrets/radsec/ca.pem
```

Set the platform values before generating a new MikroTik provisioning script:

```text
RADIUS_TRANSPORT=radsec
RADIUS_RADSEC_HOST=<VPS public IPv4>
RADIUS_RADSEC_PORT=2083
RADIUS_RADSEC_TLS_CERT_FILE=/run/secrets/radsec/server.pem
RADIUS_RADSEC_TLS_KEY_FILE=/run/secrets/radsec/server-key.pem
RADIUS_RADSEC_TLS_CA_FILE=/run/secrets/radsec/ca.pem
```

`RADIUS_RADSEC_HOST` must be the VPS IPv4 address. RouterOS validates the
server certificate against this address, so `server.pem` must have that value
in its IP subject-alternative-name.

## Certificates

Use a private CA and issue a separate client certificate for every router.
Keep the CA key only in the platform's secret store. A certificate management
system such as step-ca is recommended for a production fleet. The outline
below shows the required certificate roles, not a replacement for
key-management policy:

```text
ca.pem / ca-key.pem              private CA
server.pem / server-key.pem      serverAuth, SAN IP:<VPS public IPv4>
router-<id>.pem / router-<id>.key  clientAuth, issued automatically by Expressnet
router-<id>.p12                  generated and imported by the provisioning command
```

Set `RADSEC_CA_CERT_PEM_B64` and `RADSEC_CA_KEY_PEM_B64` only in the Railway
platform service. `RADSEC_CA_CERT_PEM_B64` is the base64 representation of
`ca.pem`; `RADSEC_CA_KEY_PEM_B64` is the base64 representation of `ca-key.pem`.
Do not set these in a tenant profile or on the VPS. The VPS holds only
`ca.pem`, `server.pem`, and `server-key.pem`.

When a tenant links a router, the one-time provisioning command downloads and
imports the CA and a unique client certificate bundle automatically. The tenant
does not enter a RADIUS host, port, shared secret, or certificate name. The
command adds:

```routeros
/radius add service=ppp,hotspot protocol=radsec address=<VPS_IP> \
  certificate=<PLATFORM_ISSUED_CERT> secret=radsec comment="Expressnet radius"
/ppp aaa set use-radius=yes
/ip hotspot profile set [find name="Expressnet-profile"] use-radius=yes radius-accounting=yes
```

RouterOS forces the RadSec shared secret to `radsec`; the security boundary is
mutual TLS, not a per-router UDP shared secret. The gateway forwards the
client-certificate identity as the RADIUS NAS identifier, so tenants remain
separated even when routers share a CGNAT address.

## Verification

On the router:

```routeros
/radius print detail where comment="Expressnet radius"
/radius monitor [find comment="Expressnet radius"]
```

The status should show `TLS connected`; check that `accepts` rises when a paid
customer logs in. On the VPS, the logs must show both the RadSec proxy request
and the Django `Access-Accept` entry. Do not enable `use-radius` manually
before the client certificate and TCP 2083 reachability are verified.
