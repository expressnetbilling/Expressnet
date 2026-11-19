from django.test import SimpleTestCase

from network.api.v1.views import _router_dns_bootstrap


class RouterDnsBootstrapTests(SimpleTestCase):
    def test_enables_resolver_and_falls_back_to_public_dns(self):
        snippet = _router_dns_bootstrap("expressnetbilling.com")
        self.assertIn("allow-remote-requests=yes", snippet)
        self.assertIn(':resolve "expressnetbilling.com"', snippet)
        self.assertIn("servers=1.1.1.1,8.8.8.8", snippet)


class CaptiveRepairScriptTests(SimpleTestCase):
    def _script(self, repair):
        from network.api.v1.views import _build_agent_port_assignment_script

        return _build_agent_port_assignment_script(
            ["wlan1", "ether3"], "Expressnet-bridge", service_type="hotspot",
            tenant={"business_name": "Shop"}, portal_url="https://x/portal", repair=repair,
        )

    def test_repair_does_not_disconnect_clients(self):
        script = self._script(True)
        self.assertNotIn("registration-table remove", script)
        self.assertIn(':if ([:len [/interface bridge port find interface="ether3"', script)
        self.assertNotIn('\n:do { /interface bridge port remove [find interface="ether3"] }', script)
        self.assertIn('place-before=[find comment="defconf: drop all not coming from LAN"] comment="billing-saas allow hotspot web-proxy"', script)

    def test_initial_assignment_still_reconnects_clients(self):
        script = self._script(False)
        self.assertIn("registration-table remove", script)
        self.assertIn('\n:do { /interface bridge port remove [find interface="ether3"] }', script)
