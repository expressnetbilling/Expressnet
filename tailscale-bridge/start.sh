#!/bin/sh
# Railway Tailscale bridge entrypoint.
#
#   TS_AUTHKEY      required  reusable (ideally tagged/ephemeral) auth key
#   TS_HOSTNAME     optional  node name, default railway-bridge
#   PORT_FORWARDS   optional  static TCP forwards, comma-separated
#                             local_port:remote_host:remote_port
#                             e.g. 18728:100.64.0.7:8728. Not needed by the web
#                             app, which reaches routers dynamically through the
#                             SOCKS5 proxy on :1055 (TAILSCALE_SOCKS5_PROXY).
#   TS_STATE_DIR    optional  default /var/lib/tailscale (mount a volume to keep
#                             the node identity across redeploys)
#
# Routes are never accepted or advertised: every router is an endpoint with
# its own 100.x.y.z address. Each optional forward is a plain TCP listener on 0.0.0.0:<local_port> that dials
# <remote_host>:<remote_port> through tailscaled (`tailscale nc`), so ordinary
# TCP clients (RouterOS API, SSH, HTTPS) can use
# <this-service>.railway.internal:<local_port> with no proxy support.
# (socat has no SOCKS5 client, so it cannot talk to --socks5-server directly.)
set -eu

: "${TS_AUTHKEY:?TS_AUTHKEY is required}"
TS_HOSTNAME="${TS_HOSTNAME:-railway-bridge}"
TS_STATE_DIR="${TS_STATE_DIR:-/var/lib/tailscale}"
SOCKET=/var/run/tailscale/tailscaled.sock
mkdir -p "$TS_STATE_DIR" /var/run/tailscale

pids=""
cleanup() {
  for p in $pids; do kill "$p" 2>/dev/null || true; done
}
trap cleanup INT TERM

tailscaled \
  --tun=userspace-networking \
  --state="$TS_STATE_DIR/tailscaled.state" \
  --socket="$SOCKET" \
  --socks5-server=0.0.0.0:1055 \
  --outbound-http-proxy-listen=0.0.0.0:1056 &
pids="$pids $!"

i=0
until tailscale --socket="$SOCKET" version >/dev/null 2>&1 && [ -S "$SOCKET" ]; do
  i=$((i + 1))
  [ "$i" -gt 30 ] && { echo "tailscaled did not start" >&2; exit 1; }
  sleep 1
done

# shellcheck disable=SC2086
tailscale --socket="$SOCKET" up \
  --authkey="$TS_AUTHKEY" \
  --hostname="$TS_HOSTNAME" \
  ${TS_EXTRA_ARGS:-}

echo "tailscale up as $TS_HOSTNAME: $(tailscale --socket="$SOCKET" ip -4 2>/dev/null | head -n1)"

if [ -n "${PORT_FORWARDS:-}" ]; then
  old_ifs="$IFS"; IFS=','
  for spec in $PORT_FORWARDS; do
    IFS="$old_ifs"
    spec=$(printf '%s' "$spec" | tr -d ' ')
    [ -z "$spec" ] && continue
    local_port=${spec%%:*}
    rest=${spec#*:}
    remote_port=${rest##*:}
    remote_host=${rest%:*}
    case "$local_port$remote_port" in *[!0-9]*|'') echo "bad PORT_FORWARDS entry: $spec" >&2; exit 1;; esac
    if [ "$rest" = "$spec" ] || [ -z "$remote_host" ] || [ "$remote_host" = "$rest" ]; then
      echo "bad PORT_FORWARDS entry (want local_port:remote_ip:remote_port): $spec" >&2; exit 1
    fi
    echo "forward 0.0.0.0:$local_port -> $remote_host:$remote_port"
    socat "TCP-LISTEN:$local_port,fork,reuseaddr" \
      "EXEC:tailscale --socket=$SOCKET nc $remote_host $remote_port" &
    pids="$pids $!"
    IFS=','
  done
  IFS="$old_ifs"
fi

# Exit (so Railway restarts us) as soon as tailscaled or any listener dies.
while :; do
  for p in $pids; do
    kill -0 "$p" 2>/dev/null || { echo "process $p exited" >&2; cleanup; exit 1; }
  done
  sleep 5
done
