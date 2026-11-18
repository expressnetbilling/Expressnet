# Docker RadSec service

Expressnet now runs RADIUS inside the application container rather than on a
separately managed RADIUS machine. FreeRADIUS accepts mutually authenticated
RadSec over TCP and proxies only inside the container to the Django AAA process
over loopback UDP.

```text
MikroTik -- mutual TLS / TCP --> radius container --> Django AAA
```

## Railway deployment (no separate VPS)

The repository-root `Dockerfile` runs the existing HTTP/API server and RadSec
in the same Railway service. In that service:

1. Use the Dockerfile builder (the repository-root `Dockerfile`).
2. Attach a Railway volume at `/run/expressnet-radsec`.
3. In **Networking**, create a **TCP Proxy** with application port `2083`.
4. Redeploy once the TCP Proxy is active.

Railway automatically injects the proxy domain and external port. Expressnet
uses them in new router provisioning commands and puts the proxy domain in the
server certificate. No RADIUS hostname, port, certificate, CA, or shared
secret variable needs to be entered.

The attached volume is required: it retains the private CA and server key
across deploys, so router client certificates stay valid.

## Docker Compose deployment

The service derives its public certificate name from the Railway TCP proxy
when available, otherwise `PUBLIC_APP_URL`. It creates a private CA and server
certificate on first start, and stores them in the named `radsec-pki` volume.
The web service reads that volume to automatically issue the client certificate
imported by each router provisioning command.

```bash
docker compose up -d --build radius
docker compose logs -f radius
```

There are no RADIUS address, port, shared-secret, PEM, CA, or base64 variables
to enter for the normal one-host deployment. Do not delete `radsec-pki`: doing so
replaces the CA and makes previously provisioned router client certificates
invalid.

## Network requirement

The Docker host (or its TCP load balancer) must route the hostname in
`PUBLIC_APP_URL` on **TCP 2083** to the `radius` service. This is a network
route, not an application variable. No UDP RADIUS ports are published. On
Railway, the TCP Proxy supplies the route and can use its automatically
assigned external port.

An HTTP-only proxy cannot carry RadSec; a raw TCP proxy is required.

If the RadSec endpoint intentionally has a different public name, set the
optional `RADIUS_RADSEC_HOST` override before first start. Its DNS name must
also route TCP traffic to the service.

## Verification

```bash
docker compose ps
docker compose logs --tail=100 radius
```

On a provisioned router, `/radius monitor` should report `TLS connected`.
The container log should then show the RadSec proxy request followed by the
Django `Access-Accept` or `Access-Reject` decision.
