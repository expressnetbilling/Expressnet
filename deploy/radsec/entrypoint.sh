#!/bin/sh
set -eu

: "${RADIUS_RADSEC_TLS_CERT_FILE:?Set RADIUS_RADSEC_TLS_CERT_FILE to the server certificate path}"
: "${RADIUS_RADSEC_TLS_KEY_FILE:?Set RADIUS_RADSEC_TLS_KEY_FILE to the server private-key path}"
: "${RADIUS_RADSEC_TLS_CA_FILE:?Set RADIUS_RADSEC_TLS_CA_FILE to the CA certificate path}"

export RADIUS_HOST=127.0.0.1
export RADIUS_AUTH_PORT=1812
export RADIUS_ACCT_PORT=1813
export RADIUS_PROXY_HOST=127.0.0.1
export RADIUS_PROXY_SHARED_SECRET="${RADIUS_PROXY_SHARED_SECRET:-radsec}"
export RADIUS_RADSEC_LISTEN_PORT="${RADIUS_RADSEC_LISTEN_PORT:-2083}"

python manage.py runradius --settings=billing_saas_django.Settings.production \
  --host "$RADIUS_HOST" --auth-port "$RADIUS_AUTH_PORT" --acct-port "$RADIUS_ACCT_PORT" &
radius_pid=$!

shutdown() {
  kill "$radius_pid" 2>/dev/null || true
  wait "$radius_pid" 2>/dev/null || true
}
trap shutdown INT TERM EXIT

exec freeradius -f -d /etc/freeradius/3.0
