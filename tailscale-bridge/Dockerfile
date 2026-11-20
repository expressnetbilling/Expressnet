# Tailscale bridge for Railway: joins the tailnet in userspace-networking mode
# (no NET_ADMIN, no /dev/net/tun, no inbound UDP) and exposes tailnet TCP
# targets on Railway private networking via local listeners.
FROM tailscale/tailscale:stable

RUN apk add --no-cache socat

COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

# SOCKS5 and HTTP proxy (tailnet access for clients that support proxies).
EXPOSE 1055 1056

ENTRYPOINT ["/usr/local/bin/start.sh"]
