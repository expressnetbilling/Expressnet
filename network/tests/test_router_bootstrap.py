from django.test import SimpleTestCase

from network.api.v1.views import _router_dns_bootstrap


class RouterDnsBootstrapTests(SimpleTestCase):
    def test_enables_resolver_and_falls_back_to_public_dns(self):
        snippet = _router_dns_bootstrap("expressnetbilling.com")
        self.assertIn("allow-remote-requests=yes", snippet)
        self.assertIn(':resolve "expressnetbilling.com"', snippet)
        self.assertIn("servers=1.1.1.1,8.8.8.8", snippet)


class RadsecNasIdentityTests(SimpleTestCase):
    def test_uses_a_stable_non_routable_address_per_client_certificate(self):
        from network.api.v1.views import _radsec_nas_placeholder

        payload = {"radsec_client_id": "router-client-1"}
        address = _radsec_nas_placeholder(payload)
        self.assertEqual(address, _radsec_nas_placeholder(payload))
        self.assertTrue(address.startswith("198.18.") or address.startswith("198.19."))


class AgentPollIntervalTests(SimpleTestCase):
    def test_interval_is_configurable_and_clamped(self):
        from django.test import override_settings
        from network.api.v1.views import _agent_poll_interval

        with override_settings(ROUTER_AGENT_POLL_SECONDS=2):
            self.assertEqual(_agent_poll_interval(), "2s")
        with override_settings(ROUTER_AGENT_POLL_SECONDS=5):
            self.assertEqual(_agent_poll_interval(), "5s")
        with override_settings(ROUTER_AGENT_POLL_SECONDS=0):
            self.assertEqual(_agent_poll_interval(), "2s")
        with override_settings(ROUTER_AGENT_POLL_SECONDS=1):
            self.assertEqual(_agent_poll_interval(), "2s")
        with override_settings(ROUTER_AGENT_POLL_SECONDS=999):
            self.assertEqual(_agent_poll_interval(), "60s")


class SubscriberPasswordTests(SimpleTestCase):
    def test_pppoe_generated_password_can_be_short_and_readable(self):
        from management.api.v1.views import _generate_customer_password

        password = _generate_customer_password(6)
        self.assertEqual(len(password), 6)
        self.assertRegex(password, r"^[ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789]+$")


class AgentRadsecScriptTests(SimpleTestCase):
    def test_radsec_client_uses_resolved_address_and_only_enables_remote_aaa_when_ready(self):
        from network.services.provisioning import _build_port_command_script

        script = _build_port_command_script(
            "ether3",
            "hotspot",
            "default",
            "https://portal.example/api/captive/tenant-1",
            bridge_name="Expressnet-bridge",
            tenant={
                "business_name": "Example ISP",
                "radius_radsec_host": "radius.example.org",
            },
            radius_enabled=True,
        )

        self.assertIn(':resolve "radius.example.org"', script)
        self.assertIn("address=$billingRadiusAddress", script)
        self.assertIn('comment="Expressnet radius"', script)
        self.assertIn("expressnet-radsec-", script)
        self.assertIn("use-radius=$billingRadiusReady", script)
        self.assertNotIn("billing-saas-radsec", script)


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


class CaptiveRepairQueueTests(SimpleTestCase):
    def test_null_hotspot_snapshot_does_not_crash(self):
        # A router snapshot with "hotspot_servers": null used to raise
        # TypeError on every agent poll, so the captive repair never queued.
        from network.api.v1.views import _queue_agent_captive_portal_repair

        for snapshot in ({"hotspot_servers": None}, {}, None):
            tenant = {"extra": {"mikrotik_router_snapshot": snapshot}, "router_port_assignments": {}}
            self.assertFalse(_queue_agent_captive_portal_repair("1", tenant, "https://example.com"))
