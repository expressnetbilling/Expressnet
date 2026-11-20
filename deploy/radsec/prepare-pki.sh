#!/bin/sh
# Create the RadSec CA and server certificate once, in the mounted volume.
# The same volume is mounted read-only by the Django service so it can issue
# the per-router client certificates used by the provisioning command.
set -eu

pki_dir="${RADSEC_PKI_DIR:-/run/expressnet-radsec}"
umask 077
mkdir -p "$pki_dir"

# The public RadSec name normally comes from the platform-provided domain. A
# manual override remains available for installations where the application
# and RadSec use different public names.
radsec_host="${RADIUS_RADSEC_HOST:-${RADSEC_PUBLIC_HOST:-${RAILWAY_TCP_PROXY_DOMAIN:-${RAILWAY_PUBLIC_DOMAIN:-}}}}"
if [ -z "$radsec_host" ] && [ -n "${PUBLIC_APP_URL:-}" ]; then
    radsec_host="$(python -c 'from urllib.parse import urlparse; import os; print(urlparse(os.environ["PUBLIC_APP_URL"]).hostname or "")')"
fi

if [ -z "$radsec_host" ]; then
    echo "RadSec needs a public DNS name. Set PUBLIC_APP_URL (preferred) or RADIUS_RADSEC_HOST." >&2
    exit 1
fi

export RADIUS_RADSEC_HOST="$radsec_host"

# A CA supplied through RADSEC_CA_CERT_PEM_B64 / RADSEC_CA_KEY_PEM_B64 wins over
# the volume. Railway volumes cannot be shared between services, so when the
# web service (which issues router client certificates) and this service are
# separate, both are given the same CA through these variables.
if [ -n "${RADSEC_CA_CERT_PEM_B64:-}" ] && [ -n "${RADSEC_CA_KEY_PEM_B64:-}" ]; then
    printf '%s' "$RADSEC_CA_CERT_PEM_B64" | base64 -d > "$pki_dir/ca.pem.new"
    printf '%s' "$RADSEC_CA_KEY_PEM_B64" | base64 -d > "$pki_dir/ca-key.pem.new"
    if ! openssl x509 -in "$pki_dir/ca.pem.new" -noout 2>/dev/null; then
        rm -f "$pki_dir/ca.pem.new" "$pki_dir/ca-key.pem.new"
        echo "RADSEC_CA_CERT_PEM_B64 is not a valid PEM certificate" >&2
        exit 1
    fi
    if ! cmp -s "$pki_dir/ca.pem.new" "$pki_dir/ca.pem" 2>/dev/null; then
        # New CA: the old server leaf is signed by a different CA.
        mv -f "$pki_dir/ca.pem.new" "$pki_dir/ca.pem"
        mv -f "$pki_dir/ca-key.pem.new" "$pki_dir/ca-key.pem"
        rm -f "$pki_dir/server.pem" "$pki_dir/server-key.pem" "$pki_dir/ca.srl"
    else
        rm -f "$pki_dir/ca.pem.new" "$pki_dir/ca-key.pem.new"
    fi
fi

if [ ! -s "$pki_dir/ca.pem" ] || [ ! -s "$pki_dir/ca-key.pem" ]; then
    openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 3650 \
        -subj "/CN=Expressnet RadSec CA" \
        -keyout "$pki_dir/ca-key.pem" -out "$pki_dir/ca.pem"
fi

# Regenerate only the public server leaf when its name changes. Router client
# certificates remain valid because the persistent CA is not replaced.
current_host="$(openssl x509 -in "$pki_dir/server.pem" -noout -ext subjectAltName 2>/dev/null || true)"
if [ ! -s "$pki_dir/server.pem" ] || [ ! -s "$pki_dir/server-key.pem" ] || ! openssl verify -CAfile "$pki_dir/ca.pem" "$pki_dir/server.pem" >/dev/null 2>&1 || ! printf '%s' "$current_host" | grep -Fq "$radsec_host"; then
    san_type="DNS"
    case "$radsec_host" in
        *:*) san_type="IP" ;;
        *.*) if printf '%s' "$radsec_host" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then san_type="IP"; fi ;;
    esac
    openssl req -newkey rsa:2048 -nodes -sha256 \
        -subj "/CN=$radsec_host" \
        -keyout "$pki_dir/server-key.pem" -out "$pki_dir/server.csr"
    extension_file="$pki_dir/server-extensions.cnf"
    printf 'basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=%s:%s\n' "$san_type" "$radsec_host" > "$extension_file"
    openssl x509 -req -sha256 -days 825 \
        -in "$pki_dir/server.csr" -CA "$pki_dir/ca.pem" -CAkey "$pki_dir/ca-key.pem" -CAcreateserial \
        -out "$pki_dir/server.pem" \
        -extfile "$extension_file"
    rm -f "$pki_dir/server.csr" "$extension_file"
fi

chmod 0400 "$pki_dir/ca-key.pem" "$pki_dir/server-key.pem"
chmod 0444 "$pki_dir/ca.pem" "$pki_dir/server.pem"
