#!/bin/sh
# Run the web/API server and the RadSec gateway in one Railway service. This
# lets the generated Railway TCP-proxy variables be used directly by both the
# provisioning API and the RADIUS listener without cross-service secrets.
set -eu

export RADSEC_PKI_DIR="${RADSEC_PKI_DIR:-/run/expressnet-radsec}"
export RADIUS_RADSEC_LISTEN_PORT=2083
export RADIUS_HOST=127.0.0.1
export RADIUS_AUTH_PORT=1812
export RADIUS_ACCT_PORT=1813
export RADIUS_PROXY_HOST=127.0.0.1
export RADIUS_PROXY_SHARED_SECRET="${RADIUS_PROXY_SHARED_SECRET:-radsec}"

/usr/local/bin/expressnet-prepare-radsec-pki
# Django and FreeRADIUS run in this same Railway service. Expose the generated
# CA paths to Django so provisioning can issue a unique client certificate for
# each router without RADSEC_CA_* environment variables.
export RADSEC_CA_CERT_FILE="$RADSEC_PKI_DIR/ca.pem"
export RADSEC_CA_KEY_FILE="$RADSEC_PKI_DIR/ca-key.pem"
export RADIUS_RADSEC_TLS_CERT_FILE="$RADSEC_PKI_DIR/server.pem"
export RADIUS_RADSEC_TLS_KEY_FILE="$RADSEC_PKI_DIR/server-key.pem"
export RADIUS_RADSEC_TLS_CA_FILE="$RADSEC_PKI_DIR/ca.pem"

python manage.py collectstatic --noinput --settings=billing_saas_django.Settings.production
python manage.py migrate --settings=billing_saas_django.Settings.production
python manage.py ensure_superuser --settings=billing_saas_django.Settings.production

python manage.py runradius --settings=billing_saas_django.Settings.production \
  --host "$RADIUS_HOST" --auth-port "$RADIUS_AUTH_PORT" --acct-port "$RADIUS_ACCT_PORT" &
radius_pid=$!

daphne --bind 0.0.0.0 --port "${PORT:-8000}" billing_saas_django.asgi:application &
web_pid=$!

shutdown() {
  kill "$radius_pid" "$web_pid" 2>/dev/null || true
  wait "$radius_pid" "$web_pid" 2>/dev/null || true
}
trap shutdown INT TERM EXIT

exec freeradius -f -d /etc/freeradius/3.0
