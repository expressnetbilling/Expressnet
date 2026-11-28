#!/bin/sh
set -eu

# This Railway service terminates RadSec inside the Django application. No
# external RADIUS daemon or localhost proxy participates in authentication.
export RADSEC_PKI_DIR="${RADSEC_PKI_DIR:-/run/expressnet-radsec}"
export RADIUS_RADSEC_LISTEN_PORT="${RADIUS_RADSEC_LISTEN_PORT:-2083}"

echo "Expressnet RADIUS: preparing TLS material"
/usr/local/bin/expressnet-prepare-radsec-pki
export RADIUS_RADSEC_TLS_CERT_FILE="${RADIUS_RADSEC_TLS_CERT_FILE:-$RADSEC_PKI_DIR/server.pem}"
export RADIUS_RADSEC_TLS_KEY_FILE="${RADIUS_RADSEC_TLS_KEY_FILE:-$RADSEC_PKI_DIR/server-key.pem}"
export RADIUS_RADSEC_TLS_CA_FILE="${RADIUS_RADSEC_TLS_CA_FILE:-$RADSEC_PKI_DIR/ca.pem}"

echo "Expressnet RADIUS: starting native RadSec listener on TCP $RADIUS_RADSEC_LISTEN_PORT"
exec python manage.py runradsec --settings=billing_saas_django.Settings.production \
  --host "${RADIUS_RADSEC_BIND_HOST:-0.0.0.0}" --port "$RADIUS_RADSEC_LISTEN_PORT"
