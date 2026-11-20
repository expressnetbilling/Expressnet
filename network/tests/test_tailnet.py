import socket
import threading

from django.test import SimpleTestCase, override_settings
from unittest import mock

from network.services import tailnet
from network.services import provisioning


class _FakeSocks5(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.request = None

    def run(self):
        conn, _ = self.server.accept()
        assert conn.recv(3) == b"\x05\x01\x00"
        conn.sendall(b"\x05\x00")
        head = conn.recv(4)
        if head[3] == 3:
            n = conn.recv(1)[0]
            host = conn.recv(n).decode()
        else:
            host = socket.inet_ntoa(conn.recv(4))
        port = int.from_bytes(conn.recv(2), "big")
        self.request = (host, port)
        conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        conn.sendall(conn.recv(16) or b"")
        conn.close()
        self.server.close()


class TailnetProxyTests(SimpleTestCase):
    def test_connects_by_magicdns_name_and_by_ip(self):
        for target in ("router-abc", "100.101.102.103"):
            fake = _FakeSocks5()
            fake.start()
            sock = tailnet.socks5_connect(("127.0.0.1", fake.port), target, 8728, timeout=3)
            sock.sendall(b"ping")
            self.assertEqual(sock.recv(4), b"ping")
            sock.close()
            fake.join(3)
            self.assertEqual(fake.request, (target, 8728))

    def test_is_tailnet_host(self):
        self.assertTrue(tailnet.is_tailnet_host("100.64.0.1"))
        self.assertTrue(tailnet.is_tailnet_host("router-1.tail1234.ts.net"))
        self.assertFalse(tailnet.is_tailnet_host("192.168.88.1"))
        self.assertFalse(tailnet.is_tailnet_host("router-1"))

    def test_proxy_address_parsing(self):
        with mock.patch.dict("os.environ", {"TAILSCALE_SOCKS5_PROXY": "tailscale-bridge.railway.internal:1055"}):
            self.assertEqual(tailnet.proxy_address(), ("tailscale-bridge.railway.internal", 1055))
        with mock.patch.dict("os.environ", {"TAILSCALE_SOCKS5_PROXY": "socks5://bridge"}):
            self.assertEqual(tailnet.proxy_address(), ("bridge", 1055))
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("TAILSCALE_SOCKS5_PROXY", None)
            self.assertIsNone(tailnet.proxy_address())


class TailnetCredentialsTests(SimpleTestCase):
    tenant = {"id": "t1", "mikrotik_user": "api", "mikrotik_pass": "pw", "mikrotik_host": "10.8.0.5", "mikrotik_tailscale_host": "router-t1"}

    def test_tailscale_host_goes_through_proxy(self):
        manager = provisioning.RouterConnectionManager()
        with mock.patch.dict("os.environ", {"TAILSCALE_SOCKS5_PROXY": "bridge:1055"}):
            creds, _ = manager.credentials_for(self.tenant)
        self.assertEqual((creds.host, creds.proxy), ("router-t1", ("bridge", 1055)))

    def test_without_bridge_falls_back_to_direct_host(self):
        manager = provisioning.RouterConnectionManager()
        import os
        with mock.patch.dict("os.environ", {}):
            os.environ.pop("TAILSCALE_SOCKS5_PROXY", None)
            creds, _ = manager.credentials_for(self.tenant)
        self.assertEqual((creds.host, creds.proxy), ("10.8.0.5", None))
