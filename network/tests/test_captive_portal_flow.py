from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory, override_settings
from rest_framework.response import Response

from network.api.v1 import views as portal_views
from network.services.provisioning import captive_portal_url, hotspot_login_redirect_html


class _MemoryRef:
    """Small Firebase-ref stand-in for captive portal request tests."""

    def __init__(self, storage, path):
        self.storage = storage
        self.path = path

    def get(self):
        return deepcopy(self.storage.get(self.path))

    def update(self, values):
        self.storage.setdefault(self.path, {}).update(values)


class CaptivePortalFlowTests(SimpleTestCase):
    tenant_id = "tenant-1"
    payment_id = "payment-1"

    def setUp(self):
        self.factory = RequestFactory()
        self.storage = {
            f"tenants/{self.tenant_id}": {"business_name": "Example ISP", "status": "active"},
            f"tenants/{self.tenant_id}/payments/{self.payment_id}": {
                "status": "success",
                "access_status": "active",
                "access_username": "254700000000",
                "access_password": "paid-password",
                "package_name": "Daily Wi-Fi",
                "access_expires_at": "2030-01-01T00:00:00+00:00",
                "link_login": "http://192.168.88.1/login",
                "dst": "https://example.org/continue",
            },
        }

    def ref(self, path):
        return _MemoryRef(self.storage, path)

    def test_router_hotspot_login_page_redirects_to_portal_with_context(self):
        page = hotspot_login_redirect_html("https://portal.example/api/captive/tenant-1")

        self.assertIn("https://portal.example/api/captive/tenant-1", page)
        self.assertIn("ip=$(ip)", page)
        self.assertIn("mac=$(mac)", page)
        self.assertIn("link_login=$(link-login)", page)
        self.assertIn("dst=$(link-orig)", page)

    @override_settings(DEBUG=False, TENANT_BASE_DOMAIN="expressnetbilling.com", PUBLIC_APP_URL="https://expressnetbilling.com")
    def test_provisioning_uses_the_tenant_subdomain_for_captive_portal(self):
        portal_url = captive_portal_url({"id": self.tenant_id, "subdomain": "citynet78"})

        self.assertEqual(
            portal_url,
            f"https://citynet78.expressnetbilling.com/api/captive/{self.tenant_id}",
        )

    def test_paid_portal_page_auto_submits_router_login(self):
        request = self.factory.get(
            f"/api/captive/{self.tenant_id}",
            {"payment_id": self.payment_id, "ip": "192.168.88.20", "mac": "AA:BB:CC:DD:EE:FF"},
        )
        with patch.object(portal_views, "ref", side_effect=self.ref), patch.object(
            portal_views, "_captive_packages", return_value=[]
        ), patch.object(portal_views, "list_children", return_value=[]):
            response = portal_views.captive_portal_page(request, self.tenant_id)

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Payment successful. Internet access is ready.", body)
        self.assertIn("action='http://192.168.88.1/login'", body)
        self.assertIn("name='username' value='254700000000'", body)
        self.assertIn("name='password' value='paid-password'", body)
        self.assertIn("f.submit();}, 250)", body)

    def test_payment_confirmation_refresh_runs_activation_without_worker(self):
        payment_path = f"tenants/{self.tenant_id}/payments/{self.payment_id}"
        self.storage[payment_path] = {
            "status": "success",
            "access_status": "activation_pending",
            "access_username": "254700000000",
            "daraja_checkout_request_id": "checkout-1",
        }
        request = self.factory.get(f"/api/captive/{self.tenant_id}")
        with patch.object(portal_views, "ref", side_effect=self.ref), patch(
            "management.api.v1.views._activate_paid_access_from_portal"
        ) as activate:
            portal_views._refresh_captive_daraja_payment(
                self.tenant_id,
                {"id": self.tenant_id},
                self.payment_id,
                self.storage[payment_path],
            )

        activate.assert_called_once_with(self.tenant_id, self.payment_id)

    def test_captive_payment_page_polls_after_stk_prompt(self):
        request = self.factory.post(f"/api/captive/{self.tenant_id}/pay")
        provider_response = Response(
            {"provider": "mpesa", "paymentId": self.payment_id, "success": True}, status=201
        )
        with patch.object(portal_views, "body", return_value={
            "package_id": "package-1",
            "phone": "0700000000",
            "ip": "192.168.88.20",
            "mac": "AA:BB:CC:DD:EE:FF",
            "router_ip": "192.168.88.1",
            "link_login": "http://192.168.88.1/login",
        }), patch.object(portal_views, "_public_pay_impl", return_value=provider_response):
            response = portal_views.captive_portal_pay(request, self.tenant_id)

        body = response.content.decode()
        self.assertEqual(response.status_code, 201)
        self.assertIn("Prompt sent. Check your phone", body)
        self.assertIn(f"payment_id={self.payment_id}", body)
        self.assertIn("link_login=http%3A%2F%2F192.168.88.1%2Flogin", body)
        self.assertIn("window.location.replace", body)
