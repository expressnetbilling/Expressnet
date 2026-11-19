"""End-to-end (DB-backed) check: a successful Daraja STK callback must queue the
customer's RouterOS access for the agent in the same request, with no Celery."""
import json
import time
from unittest.mock import patch

from django.test import TestCase, RequestFactory

from billing_api.models import Tenant
from management.api.v1 import views as v
from management.services.billing import make_daraja_callback_token


class PaidAccessActivationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(email="isp@example.com", password="x", business_name="ISP")
        self.tenant.apply_data({
            "status": "active",
            "mikrotik_provisioning_status": "completed",  # agent-linked router
            "radius_enabled": False,
        })
        self.tenant.save()

    def _new_payment(self, **fields):
        base = {"status": "pending", "amount": 20, "service_type": "hotspot", "package_name": "Daily", "phone": "254700000001"}
        return str(v.ref(f"tenants/{self.tenant.pk}/payments").push({**base, **fields}).key)

    def _callback(self, payment_id, amount, code=0):
        token = make_daraja_callback_token(self.tenant.pk, payment_id)
        payload = {"Body": {"stkCallback": {
            "ResultCode": code, "ResultDesc": "ok",
            "CallbackMetadata": {"Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": "TEST123ABC"},
                {"Name": "TransactionDate", "Value": 20261119120000},
                {"Name": "PhoneNumber", "Value": 254700000001},
            ]}}}}
        request = RequestFactory().post(
            f"/api/daraja/callback/{self.tenant.pk}/{payment_id}/{token}",
            data=json.dumps(payload), content_type="application/json",
        )
        return v.daraja_callback(request, str(self.tenant.pk), payment_id, token)

    def test_successful_stk_callback_queues_router_access_immediately(self):
        pid = self._new_payment(router_client_mac="AA:BB:CC:DD:EE:01", router_client_ip="192.168.88.10")
        v.ref(f"tenants/{self.tenant.pk}/packages").push({"name": "Daily", "price": 20, "duration": 1, "duration_unit": "days", "speed": "5M/5M"})
        with patch.object(v, "_dispatch_tenant_settlement"), patch.object(v, "mark_customer_invoice_paid"), \
                patch.object(v, "_queue_paid_access_activation") as celery_fallback:
            started = time.monotonic()
            response = self._callback(pid, 20)
            elapsed = time.monotonic() - started
        self.assertEqual(response.status_code, 200)
        payment = v.ref(f"tenants/{self.tenant.pk}/payments/{pid}").get()
        self.assertEqual(payment["status"], "success")
        self.assertEqual(payment["access_status"], "queued")  # queued for the router agent
        commands = Tenant.objects.get(pk=self.tenant.pk).as_dict().get("pending_router_commands") or []
        sync = [c for c in commands if c.get("type") == "sync_secrets" and c.get("status") == "pending"]
        self.assertEqual(len(sync), 1)
        self.assertIn("254700000001", sync[0]["script"])
        # The router's very next agent poll (every 10s) must receive the script that
        # creates the paid hotspot user and binds the client MAC.
        import jwt
        from network.api.v1 import views as nv
        from network.api.v1.views import _get_jwt_secret
        agent_token = jwt.encode({"purpose": "mikrotik_agent", "tenant_id": str(self.tenant.pk)}, _get_jwt_secret("JWT_SECRET"), algorithm="HS256")
        poll = nv.router_agent_poll(RequestFactory().get(f"/api/router/agent/{agent_token}/poll", HTTP_HOST="testserver"), agent_token)
        body = poll.content.decode()
        self.assertIn("254700000001", body)
        self.assertIn("/ip hotspot user", body)
        print(f"\ncallback handled in {elapsed:.3f}s; next agent poll delivers the hotspot user script ({len(body)} bytes)")

    def test_failed_stk_does_not_grant_access(self):
        pid = self._new_payment()
        self._callback(pid, 20, code=1032)
        payment = v.ref(f"tenants/{self.tenant.pk}/payments/{pid}").get()
        self.assertEqual(payment["status"], "failed")
        commands = Tenant.objects.get(pk=self.tenant.pk).as_dict().get("pending_router_commands") or []
        self.assertEqual(commands, [])

    def test_wrong_amount_does_not_grant_access(self):
        pid = self._new_payment()
        self._callback(pid, 1)
        self.assertEqual(v.ref(f"tenants/{self.tenant.pk}/payments/{pid}").get()["status"], "failed")
