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
    def test_provisioning_uses_working_public_portal_until_subdomains_are_enabled(self):
        portal_url = captive_portal_url({"id": self.tenant_id, "subdomain": "citynet78"})

        self.assertEqual(
            portal_url,
            f"https://expressnetbilling.com/api/captive/{self.tenant_id}",
        )

    @override_settings(
        DEBUG=False,
        TENANT_BASE_DOMAIN="expressnetbilling.com",
        PUBLIC_APP_URL="https://expressnetbilling.com",
        CAPTIVE_PORTAL_TENANT_SUBDOMAINS_ENABLED=True,
    )
    def test_provisioning_uses_tenant_subdomain_only_when_enabled(self):
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
        self.assertIn("You are connected. Opening the internet now.", body)
        self.assertIn("if(f) f.submit();", body)
        self.assertNotIn('<div class="spinner"', body)

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

    def test_captive_payment_page_does_not_render_legacy_manual_payment_details(self):
        request = self.factory.post(f"/api/captive/{self.tenant_id}/pay")
        provider_response = Response(
            {
                "provider": "manual_mpesa",
                "paymentId": self.payment_id,
                "amount": 50,
                "destinationLabel": "M-Pesa Buy Goods till",
                "destination": "123456",
                "reference": "WIFI-PAYMENT1",
            },
            status=201,
        )
        with patch.object(portal_views, "body", return_value={
            "package_id": "package-1",
            "phone": "0700000000",
            "ip": "192.168.88.20",
            "mac": "AA:BB:CC:DD:EE:FF",
        }), patch.object(portal_views, "_public_pay_impl", return_value=provider_response):
            response = portal_views.captive_portal_pay(request, self.tenant_id)

        body = response.content.decode()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("M-Pesa Buy Goods till", body)
        self.assertNotIn("123456", body)
        self.assertNotIn("WIFI-PAYMENT1", body)

    def test_legacy_direct_method_initiates_an_stk_push(self):
        class PaymentRef:
            key = "payment-1"

            def __init__(self):
                self.data = None
                self.updates = {}

            def update(self, values):
                self.updates.update(values)

        class PaymentsCollection:
            def __init__(self, payment):
                self.payment = payment

            def push(self, values):
                self.payment.data = values
                return self.payment

        payment = PaymentRef()
        tenant = {
            "business_name": "Example ISP",
            "status": "active",
            "payment_methods": ["till"],
            "business_number": "123456",
        }
        package = {"id": "package-1", "name": "Daily Wi-Fi", "price": 50, "service_type": "hotspot"}

        def fake_ref(path):
            if path == f"tenants/{self.tenant_id}":
                return _MemoryRef({path: tenant}, path)
            if path == f"tenants/{self.tenant_id}/packages/package-1":
                return _MemoryRef({path: package}, path)
            if path == f"tenants/{self.tenant_id}/payments":
                return PaymentsCollection(payment)
            raise AssertionError(path)

        request = self.factory.post(f"/api/public/{self.tenant_id}/pay")
        with patch.object(portal_views, "ref", side_effect=fake_ref), patch.object(
            portal_views, "tenant_payment_collection_config", return_value={"id": self.tenant_id}
        ), patch.object(
            portal_views, "initiate_daraja_payment", return_value={"checkout_request_id": "checkout-1"}
        ) as daraja, patch.object(portal_views, "list_children", return_value=[]):
            response = portal_views._public_pay_impl(request, self.tenant_id, data={
                "package_id": "package-1",
                "phone": "0700000000",
                "payment_method": "till",
                "service_type": "hotspot",
            })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["provider"], "mpesa")
        self.assertEqual(payment.data["status"], "pending")
        self.assertEqual(payment.data["collection_account"], "platform_daraja")
        self.assertEqual(payment.data["payment_method"], "daraja_paybill")
        self.assertEqual(payment.updates["daraja_checkout_request_id"], "checkout-1")
        daraja.assert_called_once()

    def test_agent_pppoe_customer_with_fixed_ip_gets_a_simple_queue(self):
        script = portal_views._customer_secret_script({
            "username": "pppoe-user",
            "password": "secret",
            "package": "10 Mbps",
            "service_type": "pppoe",
            "ip_address": "172.30.10.20",
            "speed": "10M/10M",
            "status": "active",
        })

        self.assertIn('remote-address="172.30.10.20"', script)
        self.assertIn('name="Expressnet-pppoe-pppoe-user"', script)
        self.assertIn('target="172.30.10.20/32"', script)
        self.assertIn('max-limit="10M/10M"', script)
        self.assertIn('in-interface-list=all-ppp', script)
        self.assertIn('src-address=172.30.0.0/16', script)
        self.assertIn('src-address=172.30.0.0/16 action=masquerade', script)

    def test_agent_pppoe_customer_without_an_assigned_ip_gets_a_stable_queue_target(self):
        customer = {
            "username": "dynamic-pppoe-user",
            "password": "secret",
            "package": "10 Mbps",
            "service_type": "pppoe",
            "speed": "10M/10M",
            "status": "active",
        }
        queue_address = portal_views.pppoe_simple_queue_address(customer)
        script = portal_views._customer_secret_script(customer)

        self.assertTrue(queue_address.startswith("172.31."))
        self.assertEqual(queue_address, portal_views.pppoe_simple_queue_address(customer))
        self.assertIn(f'remote-address="{queue_address}"', script)
        self.assertIn(f'target="{queue_address}/32"', script)
        self.assertIn('name="Expressnet-pppoe-dynamic-pppoe-user"', script)

    def test_agent_static_customer_gets_a_package_simple_queue(self):
        script = portal_views._customer_secret_script({
            "username": "static-user",
            "service_type": "static",
            "ip_address": "172.30.10.10",
            "speed": "5M/5M",
            "status": "active",
        })

        self.assertIn('name="Expressnet-static-172.30.10.10"', script)
        self.assertIn('target="172.30.10.10/32"', script)
        self.assertIn('max-limit="5M/5M"', script)

    def test_agent_port_script_restores_customer_service_forwarding(self):
        script = portal_views._build_agent_port_assignment_script(
            ["ether2"],
            "Expressnet-bridge",
            service_type="pppoe",
        )

        self.assertIn('in-interface-list=all-ppp', script)
        self.assertIn('src-address=172.30.0.0/16', script)
        self.assertIn('src-address=172.30.0.0/16 action=masquerade', script)

    def test_portal_background_is_a_single_cover_layer_on_mobile(self):
        page = portal_views._html_page("Portal", "<main>test</main>").content.decode()

        self.assertIn("min-height:100dvh", page)
        self.assertIn("background-size:cover", page)
        self.assertIn("background-repeat:no-repeat", page)
