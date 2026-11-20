# Expressnet MikroTik -> Tailscale subnet router (RouterOS v7, container package)
#
# Runs tailscale/tailscale in a RouterOS container. The router needs no public
# IP and no inbound port: the container dials out to Tailscale (WireGuard with
# NAT traversal, HTTPS/DERP fallback).
#
# Requirements: arm, arm64 or x86 router with the `container` package, external
# storage (disk1) and container mode enabled once, with a physical confirmation:
#   /system/device-mode/update container=yes   (then press the reset button or
#   power-cycle within the time RouterOS prints), then reboot.
#
# Edit the three values below, then:  /import mikrotik-setup.rsc
:local tsAuthKey "tskey-auth-REPLACE_ME"
:local tsHostname "router-REPLACE_ME"
:local lanSubnet "192.168.88.0/24"
:local storage "disk1"

:local routes "$lanSubnet,172.17.0.1/32"

# --- Container network -------------------------------------------------------
/interface veth add name=veth-tailscale address=172.17.0.2/24 gateway=172.17.0.1
/interface bridge add name=bridge-tailscale
/ip address add address=172.17.0.1/24 interface=bridge-tailscale comment="tailscale container"
/interface bridge port add bridge=bridge-tailscale interface=veth-tailscale

# --- NAT: let the container reach the internet and local subnets -------------
/ip firewall nat add chain=srcnat action=masquerade src-address=172.17.0.0/24 \
    out-interface=!bridge-tailscale comment="tailscale container masquerade"

# --- Firewall: tailnet -> router services and LAN ----------------------------
# Placed above the default "drop all not coming from LAN" when it exists.
:do { /ip firewall filter add chain=input action=accept in-interface=bridge-tailscale \
    protocol=tcp dst-port=22,8291,8728,8729 \
    place-before=[find comment="defconf: drop all not coming from LAN"] \
    comment="tailscale -> router API/Winbox/SSH" } on-error={ \
    /ip firewall filter add chain=input action=accept in-interface=bridge-tailscale \
    protocol=tcp dst-port=22,8291,8728,8729 comment="tailscale -> router API/Winbox/SSH" }
:do { /ip firewall filter add chain=forward action=accept in-interface=bridge-tailscale \
    place-before=[find comment="defconf: drop all from WAN not DSTNATed"] \
    comment="tailscale -> LAN devices" } on-error={ \
    /ip firewall filter add chain=forward action=accept in-interface=bridge-tailscale \
    comment="tailscale -> LAN devices" }
# The API service must accept the container source address.
/ip service set api address=172.17.0.0/24
/ip service set api-ssl address=172.17.0.0/24

# --- Container ---------------------------------------------------------------
/container config set registry-url=https://registry-1.docker.io tmpdir=("$storage/pull")
/container envs add name=tailscale key=TS_AUTHKEY value=$tsAuthKey
/container envs add name=tailscale key=TS_HOSTNAME value=$tsHostname
/container envs add name=tailscale key=TS_ROUTES value=$routes
/container envs add name=tailscale key=TS_EXTRA_ARGS value=("--advertise-routes=" . $routes)
# RouterOS containers have no /dev/net/tun: use userspace networking.
/container envs add name=tailscale key=TS_USERSPACE value=true
/container envs add name=tailscale key=TS_STATE_DIR value=/var/lib/tailscale
/container mounts add name=tailscale-state src=("$storage/tailscale-state") dst=/var/lib/tailscale
/container add remote-image=tailscale/tailscale:latest interface=veth-tailscale \
    envlist=tailscale mounts=tailscale-state root-dir=("$storage/tailscale") \
    hostname=$tsHostname dns=1.1.1.1 logging=yes start-on-boot=yes \
    comment="tailscale subnet router"

# Wait for the image to extract (status=stopped), then start it:
#   /container print
#   /container start [find comment="tailscale subnet router"]
# Finally approve the advertised routes in the Tailscale Admin Console
# (Machines -> the router -> Edit route settings), see README.
#
# ---------------------------------------------------------------------------
# Routers without the container package (mipsbe / mmips, e.g. hAP lite, RB951):
# RouterOS cannot run containers. Put a small Linux sidecar on the LAN
# (OpenWrt box, Raspberry Pi, any always-on host) and run on it:
#   tailscale up --authkey=tskey-auth-... --hostname=router-REPLACE_ME \
#       --advertise-routes=192.168.88.0/24 --accept-routes
# then allow it to reach the router: /ip service set api address=<sidecar-ip>/32
# and enable IP forwarding on the sidecar (sysctl net.ipv4.ip_forward=1).
