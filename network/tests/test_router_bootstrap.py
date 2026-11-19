from django.test import SimpleTestCase

from network.api.v1.views import _router_dns_bootstrap


class RouterDnsBootstrapTests(SimpleTestCase):
    def test_enables_resolver_and_falls_back_to_public_dns(self):
        snippet = _router_dns_bootstrap("expressnetbilling.com")
        self.assertIn("allow-remote-requests=yes", snippet)
        self.assertIn(':resolve "expressnetbilling.com"', snippet)
        self.assertIn("servers=1.1.1.1,8.8.8.8", snippet)


class AgentPollIntervalTests(SimpleTestCase):
    def test_interval_is_configurable_and_clamped(self):
        from django.test import override_settings
        from network.api.v1.views import _agent_poll_interval

        with override_settings(ROUTER_AGENT_POLL_SECONDS=5):
            self.assertEqual(_agent_poll_interval(), "5s")
        with override_settings(ROUTER_AGENT_POLL_SECONDS=0):
            self.assertEqual(_agent_poll_interval(), "5s")
        with override_settings(ROUTER_AGENT_POLL_SECONDS=1):
            self.assertEqual(_agent_poll_interval(), "2s")
        with override_settings(ROUTER_AGENT_POLL_SECONDS=999):
            self.assertEqual(_agent_poll_interval(), "60s")
