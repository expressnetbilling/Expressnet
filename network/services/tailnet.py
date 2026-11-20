"""Reach routers on the tailnet through the Railway Tailscale bridge.

The bridge (``tailscale-bridge/``) runs tailscaled in userspace mode and
exposes a SOCKS5 proxy. Routers are addressed by their own tailnet identity
(``100.x.y.z`` or MagicDNS name such as ``router-<id>``); no subnet routes are
involved, so routers may all share the same LAN addressing.
"""
import ipaddress
import os
import socket
import ssl
import struct

from routeros_api import api as _ros_api
from routeros_api import api_communicator, api_socket, base_api, exceptions

_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def proxy_address():
    """Return ``(host, port)`` of the bridge SOCKS5 proxy, or None if unset."""
    raw = str(os.getenv("TAILSCALE_SOCKS5_PROXY") or "").strip()
    if not raw:
        return None
    raw = raw.split("://", 1)[-1]
    host, _, port = raw.rpartition(":")
    if not host:
        host, port = raw, "1055"
    return host, int(port)


def is_tailnet_host(host):
    host = str(host or "").strip().lower()
    if host.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(host) in _CGNAT
    except ValueError:
        return False


def socks5_connect(proxy, host, port, timeout=15.0):
    """Open a TCP connection to host:port through a SOCKS5 proxy (no auth)."""
    sock = socket.create_connection(proxy, timeout=timeout)
    try:
        sock.sendall(b"\x05\x01\x00")
        if _recv(sock, 2) != b"\x05\x00":
            raise OSError("SOCKS5 proxy refused no-auth negotiation")
        try:
            addr = b"\x01" + ipaddress.IPv4Address(host).packed
        except ValueError:
            name = host.encode("idna")
            if len(name) > 255:
                raise OSError("hostname too long for SOCKS5")
            addr = b"\x03" + bytes([len(name)]) + name
        sock.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", int(port)))
        head = _recv(sock, 4)
        if head[0] != 5 or head[1] != 0:
            raise OSError(f"SOCKS5 connect to {host}:{port} failed (code {head[1]})")
        atyp = head[3]
        if atyp == 1:
            _recv(sock, 4 + 2)
        elif atyp == 4:
            _recv(sock, 16 + 2)
        elif atyp == 3:
            _recv(sock, _recv(sock, 1)[0] + 2)
        else:
            raise OSError("SOCKS5 proxy sent an unknown address type")
        return sock
    except Exception:
        sock.close()
        raise


def _recv(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise OSError("SOCKS5 proxy closed the connection")
        data += chunk
    return data


class ProxiedRouterOsApiPool(_ros_api.RouterOsApiPool):
    """RouterOsApiPool whose sockets are opened through the SOCKS5 bridge."""

    proxy = None

    def get_api(self):
        if not self.connected:
            try:
                raw = socks5_connect(self.proxy, self.host, self.port, timeout=self.socket_timeout)
            except OSError as exc:
                raise exceptions.RouterOsApiConnectionError(exc)
            api_socket.set_keepalive(raw, after_idle_sec=10)
            if self.use_ssl:
                ctx = self.ssl_context or ssl.create_default_context()
                if self.ssl_context is None:
                    ctx.check_hostname = bool(self.ssl_verify and self.ssl_verify_hostname)
                    ctx.verify_mode = ssl.CERT_REQUIRED if self.ssl_verify else ssl.CERT_NONE
                raw = ctx.wrap_socket(raw, server_hostname=self.host)
            self.socket = api_socket.SocketWrapper(raw)
            communicator = api_communicator.ApiCommunicator(base_api.Connection(self.socket))
            self.api = _ros_api.RouterOsApi(communicator)
            for handler in self._get_exception_handlers():
                communicator.add_exception_handler(handler)
            self.api.login(self.username, self.password, self.plaintext_login)
            self.connected = True
        return self.api
