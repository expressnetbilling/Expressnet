"""WebSocket events connecting RouterOS work to the Expressnet UI.

RouterOS' native API remains a server-to-router binary TCP connection.  This
module deliberately has a separate responsibility: it publishes the outcome
of that work to dashboard and captive-portal browsers through Django Channels.
"""

import logging
import re

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer

from billing_api.models import Payment, Tenant
from billing_api.services import decode_tenant_token, verify_payment_access_token


logger = logging.getLogger(__name__)
_GROUP_VALUE = re.compile(r"[^A-Za-z0-9.-]")


def _group_value(value):
    """Channel layer group names only permit letters, digits, dots and dashes."""
    return _GROUP_VALUE.sub("-", str(value or ""))[:80] or "unknown"


def tenant_group_name(tenant_id):
    return f"tenant.{_group_value(tenant_id)}"


def payment_group_name(tenant_id, payment_id):
    return f"payment.{_group_value(tenant_id)}.{_group_value(payment_id)}"


def publish_realtime_event(tenant_id, event_type, data=None, payment_id=None):
    """Publish a small, non-secret state event after a committed operation.

    Publishing failure must never roll back router provisioning or payment
    activation. Consumers can always refresh the ordinary REST resource after
    receiving an event, which keeps the WebSocket payload intentionally small.
    """
    payload = {
        "type": str(event_type),
        "tenant_id": str(tenant_id),
        "data": data or {},
    }
    layer = get_channel_layer()
    if layer is None:
        return
    groups = [tenant_group_name(tenant_id)]
    if payment_id:
        groups.append(payment_group_name(tenant_id, payment_id))
    try:
        for group in groups:
            async_to_sync(layer.group_send)(group, {"type": "realtime.event", "payload": payload})
    except Exception:
        logger.warning("Realtime event publish failed tenant=%s type=%s", tenant_id, event_type, exc_info=True)


def _offered_bearer_token(scope):
    """Read credentials from the WebSocket subprotocol, never its URL."""
    protocols = scope.get("subprotocols") or []
    if len(protocols) >= 2 and protocols[0] == "bearer":
        return protocols[1]
    return ""


@database_sync_to_async
def _active_tenant(tenant_id):
    return Tenant.objects.filter(pk=tenant_id, status="active").exists()


@database_sync_to_async
def _payment_belongs_to_tenant(tenant_id, payment_id):
    return Payment.objects.filter(pk=payment_id, tenant_id=tenant_id).exists()


class TenantRealtimeConsumer(AsyncJsonWebsocketConsumer):
    """Authenticated tenant dashboard event stream."""

    async def connect(self):
        token = _offered_bearer_token(self.scope)
        try:
            decoded = decode_tenant_token(token)
            tenant_id = str(decoded.get("id") or "")
        except Exception:
            tenant_id = ""
        if not tenant_id or not await _active_tenant(tenant_id):
            await self.close(code=4401)
            return
        self.tenant_id = tenant_id
        self.group_name = tenant_group_name(tenant_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept("bearer")
        await self.send_json({"type": "realtime.connected", "tenant_id": tenant_id})

    async def disconnect(self, close_code):
        if getattr(self, "group_name", None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def realtime_event(self, event):
        await self.send_json(event["payload"])


class PaymentRealtimeConsumer(AsyncJsonWebsocketConsumer):
    """A scoped stream for one captive-portal payment verification token."""

    async def connect(self):
        tenant_id = str(self.scope["url_route"]["kwargs"].get("tenant_id") or "")
        payment_id = str(self.scope["url_route"]["kwargs"].get("payment_id") or "")
        token = _offered_bearer_token(self.scope)
        if (
            not tenant_id
            or not payment_id
            or not verify_payment_access_token(tenant_id, payment_id, token)
            or not await _payment_belongs_to_tenant(tenant_id, payment_id)
        ):
            await self.close(code=4401)
            return
        self.group_name = payment_group_name(tenant_id, payment_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept("bearer")
        await self.send_json({"type": "realtime.connected", "payment_id": payment_id})

    async def disconnect(self, close_code):
        if getattr(self, "group_name", None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def realtime_event(self, event):
        await self.send_json(event["payload"])
