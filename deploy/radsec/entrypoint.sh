#!/bin/sh
set -eu

# This Railway service is the RADIUS server.  It runs the application's Django
# AAA implementation directly; no proxy or external RADIUS daemon is involved.
export RADIUS_HOST="${RADIUS_HOST:-0.0.0.0}"
export RADIUS_AUTH_PORT="${RADIUS_AUTH_PORT:-1812}"
export RADIUS_ACCT_PORT="${RADIUS_ACCT_PORT:-1813}"

echo "Expressnet RADIUS: starting Django AAA on $RADIUS_HOST:$RADIUS_AUTH_PORT/$RADIUS_ACCT_PORT"
exec python manage.py runradius --settings=billing_saas_django.Settings.production \
  --host "$RADIUS_HOST" --auth-port "$RADIUS_AUTH_PORT" --acct-port "$RADIUS_ACCT_PORT"
