# Expressnet MikroTik -> Tailscale endpoint (RouterOS v7, container package)
#
# The router joins the tailnet as an ENDPOINT with its own unique 100.x.y.z
# address. No subnet routes are advertised, so any number of routers can use
# the same local addressing (192.168.88.0/24, 172.17.0.0/24) without clashing.
# The Railway bridge reaches this router at its tailnet name (router-<id>) and
# `tailscale serve` inside the container forwards the management ports to the
# router itself at 172.17.0.1. No public IP and no inbound port are needed.
#
# Requirements: arm, arm64 or x86 router with the `container` package and
# external storage (disk1). Enable container mode once, with a physical
# confirmation, then reboot:
#   /system/device-mode/update container=yes
#
# Edit the values below, then:  /import mikrotik-setup.rsc
:local tsAuthKey "tskey-auth-REPLACE_ME"
:local tsHostname "router-REPLACE_ME"
:local storage "disk1"
# Optional: provisioning callback URL of this tenant (from the Expressnet
# provisioning command). When set, the router reports its tailnet name to
# Expressnet so the app can find it. Leave empty to set it by hand instead.
:local callbackUrl ""

# --- Container network (local only; never advertised) -------------------------
/interface veth add name=veth-tailscale address=172.17.0.2/24 gateway=172.17.0.1
/interface bridge add name=bridge-tailscale
/ip address add address=172.17.0.1/24 interface=bridge-tailscale comment="tailscale container"
/interface bridge port add bridge=bridge-tailscale interface=veth-tailscale

# Let the container reach the internet (Tailscale control plane and DERP).
/ip firewall nat add chain=srcnat action=masquerade src-address=172.17.0.0/24 \
    out-interface=!bridge-tailscale comment="tailscale container masquerade"

# --- Firewall: management ports from the container only -----------------------
# Traffic arriving over the tailnet is forwarded by tailscale serve to
# 172.17.0.1, so it reaches the router as input from 172.17.0.0/24.
:do { /ip firewall filter add chain=input action=accept in-interface=bridge-tailscale \
    src-address=172.17.0.0/24 protocol=tcp dst-port=22,443,8728,8729 \
    place-before=[find comment="defconf: drop all not coming from LAN"] \
    comment="tailscale container -> router API/REST/SSH" } on-error={ \
    /ip firewall filter add chain=input action=accept in-interface=bridge-tailscale \
    src-address=172.17.0.0/24 protocol=tcp dst-port=22,443,8728,8729 \
    comment="tailscale container -> router API/REST/SSH" }
# The RouterOS API only answers the container.
/ip service set api address=172.17.0.0/24
/ip service set api-ssl address=172.17.0.0/24
# REST/WebFig (443) needs a certificate on www-ssl:  /ip service set www-ssl disabled=no certificate=<name>

# --- tailscale serve: tailnet 100.x:port -> router 172.17.0.1:port ------------
# Alternative design (not used): a RouterOS dstnat on bridge-tailscale cannot
# see this traffic because userspace Tailscale terminates it inside the
# container, so forwarding is done by tailscaled itself.
:local serveJson "{\"TCP\":{\"22\":{\"TCPForward\":\"172.17.0.1:22\"},\"443\":{\"TCPForward\":\"172.17.0.1:443\"},\"8728\":{\"TCPForward\":\"172.17.0.1:8728\"},\"8729\":{\"TCPForward\":\"172.17.0.1:8729\"}}}"
/file add name=("$storage/tailscale-serve/serve.json") contents=$serveJson

# --- Container -----------------------------------------------------------------
/container config set registry-url=https://registry-1.docker.io tmpdir=("$storage/pull")
/container envs add name=tailscale key=TS_AUTHKEY value=$tsAuthKey
/container envs add name=tailscale key=TS_HOSTNAME value=$tsHostname
# RouterOS containers have no /dev/net/tun: userspace networking. No TS_ROUTES
# and no --advertise-routes: this node is an endpoint only.
/container envs add name=tailscale key=TS_USERSPACE value=true
/container envs add name=tailscale key=TS_STATE_DIR value=/var/lib/tailscale
/container envs add name=tailscale key=TS_SERVE_CONFIG value=/config/serve.json
/container mounts add name=tailscale-state src=("$storage/tailscale-state") dst=/var/lib/tailscale
/container mounts add name=tailscale-serve src=("$storage/tailscale-serve") dst=/config
/container add remote-image=tailscale/tailscale:latest interface=veth-tailscale \
    envlist=tailscale mounts=tailscale-state,tailscale-serve root-dir=("$storage/tailscale") \
    hostname=$tsHostname dns=1.1.1.1 logging=yes start-on-boot=yes \
    comment="tailscale endpoint"

# Tell Expressnet which tailnet name reaches this router.
:if ([:len $callbackUrl] > 0) do={
    :do { /tool fetch keep-result=no url=($callbackUrl . "&ts_host=" . $tsHostname) } on-error={ :log warning "Expressnet: tailnet callback failed" }
}

# Wait for the image to extract (status=stopped), then start it:
#   /container print
#   /container start [find comment="tailscale endpoint"]
# The router appears in the Tailscale Admin Console with its own 100.x.y.z.
# Nothing to approve: no routes are advertised.
#
# ---------------------------------------------------------------------------
# Routers without the container package (mipsbe / mmips, e.g. hAP lite, RB951):
# RouterOS cannot run containers. Run a small always-on Linux node on the LAN
# (OpenWrt box, Raspberry Pi, any host) as an endpoint, not a subnet router:
#   tailscale up --authkey=tskey-auth-... --hostname=router-REPLACE_ME
#   tailscale serve --bg --tcp 8728 tcp://<router-lan-ip>:8728
# and allow it in RouterOS: /ip service set api address=<node-ip>/32
