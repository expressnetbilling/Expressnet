#!/bin/sh
set -eu

export RADSEC_PKI_DIR="${RADSEC_PKI_DIR:-/run/expressnet-radsec}"
echo "Expressnet RadSec: preparing PKI"
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

# The package image ships its UDP default and inner-tunnel virtual servers
# enabled. They would contend with Django's loopback AAA listener on 1812/1813.
# Only the dedicated TCP/TLS RadSec virtual server belongs in this container.
rm -f /etc/freeradius/3.0/sites-enabled/default \
  /etc/freeradius/3.0/sites-enabled/inner-tunnel \
  /etc/freeradius/3.0/mods-enabled/eap

echo "Expressnet RadSec: validating FreeRADIUS configuration"
# Validate before launching the Django child. FreeRADIUS otherwise exits so
# early that Railway records only a generic restart, hiding the useful error.
if ! freeradius -XC -d /etc/freeradius/3.0 >/tmp/radsec-config-check.log 2>&1; then
  # FreeRADIUS -XC is intentionally very verbose. Keep Railway's log stream
  # below its rate limit while retaining the parser error at the end.
  tail -n 80 /tmp/radsec-config-check.log >&2
  exit 1
fi

echo "Expressnet RadSec: starting Django AAA on 127.0.0.1:1812/1813"
python manage.py runradius --settings=billing_saas_django.Settings.production \
  --host "$RADIUS_HOST" --auth-port "$RADIUS_AUTH_PORT" --acct-port "$RADIUS_ACCT_PORT" &
radius_pid=$!

echo "Expressnet RadSec: starting FreeRADIUS TLS listener on TCP $RADIUS_RADSEC_LISTEN_PORT"
freeradius -f -d /etc/freeradius/3.0 >/tmp/radsec-runtime.log 2>&1 &
radsec_pid=$!

shutdown() {
  kill "$radius_pid" "$radsec_pid" 2>/dev/null || true
  wait "$radius_pid" "$radsec_pid" 2>/dev/null || true
}
trap shutdown INT TERM EXIT

# A TLS gateway without its Django policy engine is broken just as surely as a
# dead gateway. Let Railway restart this complete pair if either child exits.
while :; do
  if ! kill -0 "$radius_pid" 2>/dev/null; then
    echo "Expressnet RadSec: Django AAA stopped; restarting service" >&2
    exit 1
  fi
  if ! kill -0 "$radsec_pid" 2>/dev/null; then
    radsec_status=1
    wait "$radsec_pid" || radsec_status=$?
    echo "Expressnet RadSec: FreeRADIUS stopped (exit $radsec_status); restarting service" >&2
    tail -n 80 /tmp/radsec-runtime.log >&2
    exit "$radsec_status"
  fi
  sleep 2
done
