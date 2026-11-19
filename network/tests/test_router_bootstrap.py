from django.test import SimpleTestCase

from network.api.v1.views import _router_dns_bootstrap


class RouterDnsBootstrapTests(SimpleTestCase):
    def test_enables_resolver_and_falls_back_to_public_dns(self):
        snippet = _router_dns_bootstrap("expressnetbilling.com")
        self.assertIn("allow-remote-requests=yes", snippet)
        self.assertIn(':resolve "expressnetbilling.com"', snippet)
        self.assertIn("servers=1.1.1.1,8.8.8.8", snippet)
