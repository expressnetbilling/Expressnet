#!/bin/sh
set -eu

export RADSEC_PKI_DIR="${RADSEC_PKI_DIR:-/run/expressnet-radsec}"
/usr/local/bin/expressnet-prepare-radsec-pki

export RADIUS_RADSEC_TLS_CERT_FILE="${RADIUS_RADSEC_TLS_CERT_FILE:-$RADSEC_PKI_DIR/server.pem}"
export RADIUS_RADSEC_TLS_KEY_FILE="${RADIUS_RADSEC_TLS_KEY_FILE:-$RADSEC_PKI_DIR/server-key.pem}"
export RADIUS_RADSEC_TLS_CA_FILE="${RADIUS_RADSEC_TLS_CA_FILE:-$RADSEC_PKI_DIR/ca.pem}"

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
