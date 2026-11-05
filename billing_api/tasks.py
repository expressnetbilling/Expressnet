from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Customer, Tenant, TenantSubscription
from .services import iso_now, list_children, normalize_phone, ref, send_sms_message, send_whatsapp_message, set_customer_enabled, upsert_customer_access, write_audit_log

"""

"""
@shared_task
def expire_tenant_subscriptions():
    now = timezone.now()
    expired = TenantSubscription.objects.select_related("tenant").filter(expires_at__lt=now).exclude(tenant__status="suspended")
    count = 0
    for subscription in expired:
        subscription.tenant.status = "suspended"
        subscription.tenant.save(update_fields=["status", "updated_at"])
        ref(f"tenants/{subscription.tenant_id}").update(
            {
                "status": "suspended",
                "suspended_reason": "expired_subscription",
                "subscription_expired_at": subscription.expires_at.isoformat() if subscription.expires_at else "",
                "updated_at": iso_now(),
            }
        )
        write_audit_log(action="AUTO_SUSPEND_EXPIRED_SUBSCRIPTION", target_id=str(subscription.tenant_id), target_type="tenant", metadata={"subscription_id": subscription.pk})
        count += 1
    return count


@shared_task
def send_subscription_reminder_sms():
    now = timezone.now()
    soon = now + timezone.timedelta(days=3)
    return TenantSubscription.objects.filter(expires_at__date=soon.date()).count()


@shared_task
def expire_customer_access():
    now = iso_now()
    count = 0
    for tenant in list_children("tenants"):
        tenant_id = tenant.get("id")
        if not tenant_id:
            continue
        for customer in list_children(f"tenants/{tenant_id}/customers"):
            expiry = str(customer.get("expiry_date") or "")
            if not expiry or expiry > now or customer.get("status") == "expired":
                continue
            service_type = customer.get("service_type") or "hotspot"
            username = customer.get("mac_address") if service_type == "tv" else customer.get("username")
            if service_type == "static":
                try:
                    upsert_customer_access({"id": tenant_id, **tenant}, customer, disabled=True)
                except Exception:
                    pass
            elif service_type != "pppoe":
                try:
                    set_customer_enabled({"id": tenant_id, **tenant}, username, service_type, False)
                except Exception:
                    pass
            ref(f"tenants/{tenant_id}/customers/{customer['id']}").update(
                {
                    "status": "expired",
                    "auto_reconnect": False,
                    "expired_at": now,
                    "updated_at": now,
                }
            )
            count += 1
    return count


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_expired_customer_invoices(self, batch_size=200):
    """Create overdue invoices in bounded batches outside customer read requests."""
    from management.api.v1.views import create_customer_invoice

    cutoff = timezone.now().isoformat()
    processed = 0
    for tenant_record in Tenant.objects.only("id", "extra").iterator(chunk_size=100):
        tenant_id = str(tenant_record.pk)
        tenant = {"id": tenant_id, **(tenant_record.extra or {})}
        customers = Customer.objects.filter(
            tenant_id=tenant_id, service_type__in=["pppoe", "static"], expiry_date__lte=cutoff,
        ).exclude(expiry_date__isnull=True).exclude(expiry_date="").order_by("expiry_date", "id")
        for customer_record in customers.iterator(chunk_size=min(batch_size, 200)):
            if processed >= batch_size:
                return processed
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=tenant_id)
                locked_customer = Customer.objects.select_for_update().filter(tenant_id=tenant_id, pk=customer_record.pk).first()
                if not locked_customer:
                    continue
                customer = locked_customer.as_dict()
                expiry = parse_datetime(str(customer.get("expiry_date") or ""))
                if not expiry:
                    continue
                marker = f"expiry_invoice_{expiry.date().isoformat()}"
                if customer.get(marker):
                    continue
                amount = customer.get("amount_payable")
                if amount in {None, ""}:
                    package = next((item for item in list_children(f"tenants/{tenant_id}/packages")
                                    if str(item.get("name") or "").strip().lower() == str(customer.get("package") or "").strip().lower()), {})
                    amount = package.get("amount_payable") or package.get("price") or 0
                invoice = create_customer_invoice(tenant, customer, amount, reason="subscription_expired", due_at=expiry.isoformat())
                if invoice:
                    ref(f"tenants/{tenant_id}/customers/{customer['id']}").update({marker: invoice["id"], "last_expiry_invoice_at": iso_now()})
                    processed += 1
    return processed


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def provision_customer_access(self, tenant_id, customer_id):
    """Apply a newly created customer to MikroTik outside the API request."""
    from network.services.provisioning import (
        RouterOSAPIError, create_hotspot_profile, create_ppp_profile, has_mikrotik_credentials,
        mikrotik_managed_bridge_name, upsert_customer_access,
    )
    from network.api.v1.views import (
        _customer_secret_script, _queue_router_command_for_tenant, _router_is_agent_linked,
    )

    tenant_record = Tenant.objects.filter(pk=tenant_id).first()
    customer_record = Customer.objects.filter(tenant_id=tenant_id, pk=customer_id).first()
    if not tenant_record or not customer_record:
        return {"status": "missing_record"}
    tenant = {"id": str(tenant_record.pk), **tenant_record.as_dict()}
    customer = customer_record.as_dict()
    service_type = str(customer.get("service_type") or "hotspot").lower()
    package = next((item for item in list_children(f"tenants/{tenant_id}/packages")
                    if str(item.get("name") or "").strip().lower() == str(customer.get("package") or "").strip().lower()), {})
    payload = {**customer, "package_name": customer.get("package"), "speed": package.get("speed"), "service_type": service_type}
    try:
        if has_mikrotik_credentials(tenant):
            logger.info("Customer provisioning using direct RouterOS API tenant=%s customer=%s", tenant_id, customer_id)
            if service_type == "pppoe":
                create_ppp_profile(tenant, package.get("name"), package.get("speed"))
            elif service_type == "hotspot":
                create_hotspot_profile(tenant, package.get("name"), package.get("speed"))
            upsert_customer_access(tenant, payload, disabled=customer.get("status") != "active")
        elif _router_is_agent_linked(tenant):
            payload.update({"package": customer.get("package"), "mikrotik_bridge_name": mikrotik_managed_bridge_name(tenant)})
            queued = _queue_router_command_for_tenant(tenant_id, {
                "type": "sync_secrets", "router_id": customer.get("mikrotik_router_id"),
                "customer_ids": [customer_id], "script": _customer_secret_script(payload),
            }, tenant)
            command_id = getattr(queued, "data", {}).get("command_id")
            logger.info("Customer provisioning queued for router agent tenant=%s customer=%s command=%s", tenant_id, customer_id, command_id)
            ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
                "provisioning_status": "queued", "provisioning_message": "Access queued for MikroTik agent sync",
            })
            return {"status": "queued"}
        message = "MikroTik is not configured and no linked router agent is available. Customer access was not provisioned."
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
            "provisioning_status": "failed", "provisioning_message": message,
        })
        logger.warning("Customer provisioning unavailable tenant=%s customer=%s", tenant_id, customer_id)
        return {"status": "failed", "message": message}
    except Exception as exc:
        logger.exception("Customer provisioning failed tenant=%s customer=%s", tenant_id, customer_id)
        if isinstance(exc, (TimeoutError, OSError, RouterOSAPIError)) and _router_is_agent_linked(tenant):
            payload.update({"package": customer.get("package"), "mikrotik_bridge_name": mikrotik_managed_bridge_name(tenant)})
            queued = _queue_router_command_for_tenant(tenant_id, {
                "type": "sync_secrets", "router_id": customer.get("mikrotik_router_id"),
                "customer_ids": [customer_id], "script": _customer_secret_script(payload),
            }, tenant)
            command_id = getattr(queued, "data", {}).get("command_id")
            logger.info("Customer provisioning fell back to router agent tenant=%s customer=%s command=%s error=%s", tenant_id, customer_id, command_id, exc)
            ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
                "provisioning_status": "queued", "provisioning_message": f"Direct RouterOS provisioning failed: {exc}. Access queued for agent sync.",
            })
            return {"status": "queued"}
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
            "provisioning_status": "failed", "provisioning_message": str(exc)[:500],
        })
        raise


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def sync_customer_access_after_update(self, tenant_id, customer_id, send_credentials=False):
    """Sync changed customer credentials/status to the router and notify asynchronously."""
    from management.api.v1.views import (
        _customer_credentials_sms, _customer_secret_script, package_data_limit_bytes,
        package_duration_delta, package_is_bundle,
    )
    from network.services.provisioning import RouterOSAPIError, has_mikrotik_credentials, mikrotik_managed_bridge_name, set_customer_enabled, upsert_customer_access
    from network.api.v1.views import _queue_router_command_for_tenant, _router_is_agent_linked

    tenant_record = Tenant.objects.filter(pk=tenant_id).first()
    customer_record = Customer.objects.filter(tenant_id=tenant_id, pk=customer_id).first()
    if not tenant_record or not customer_record:
        return {"status": "missing_record"}
    tenant = {"id": str(tenant_record.pk), **tenant_record.as_dict()}
    customer = customer_record.as_dict()
    service_type = str(customer.get("service_type") or "hotspot").lower()
    package = next((item for item in list_children(f"tenants/{tenant_id}/packages")
                    if str(item.get("name") or "").strip().lower() == str(customer.get("package") or "").strip().lower()), {})
    payload = {
        **customer, "package_name": customer.get("package"), "speed": package.get("speed"),
        "duration_seconds": None if package_is_bundle(package) else int(package_duration_delta(package).total_seconds()) if package and service_type == "hotspot" else None,
        "limit_bytes_total": package_data_limit_bytes(package),
    }
    try:
        if has_mikrotik_credentials(tenant):
            logger.info("Customer update sync using direct RouterOS API tenant=%s customer=%s", tenant_id, customer_id)
            upsert_customer_access(tenant, payload, disabled=customer.get("status") != "active")
            if service_type != "static":
                set_customer_enabled(tenant, customer.get("username"), service_type, customer.get("status") == "active")
        elif _router_is_agent_linked(tenant):
            payload["mikrotik_bridge_name"] = mikrotik_managed_bridge_name(tenant)
            queued = _queue_router_command_for_tenant(tenant_id, {
                "type": "sync_secrets", "customer_ids": [customer_id], "script": _customer_secret_script(payload),
            }, tenant)
            logger.info("Customer update sync queued for router agent tenant=%s customer=%s command=%s", tenant_id, customer_id, getattr(queued, "data", {}).get("command_id"))
        else:
            message = "MikroTik is not configured and no linked router agent is available. Customer update was not synced."
            ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
                "router_sync_status": "failed", "router_sync_error": message, "provisioning_message": message,
            })
            logger.warning("Customer update sync unavailable tenant=%s customer=%s", tenant_id, customer_id)
            return {"status": "failed", "message": message}
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update({"router_sync_status": "synced"})
        if send_credentials:
            send_sms_message(customer.get("phone"), _customer_credentials_sms(customer, tenant), tenant)
        return {"status": "synced"}
    except Exception as exc:
        logger.exception("Customer update sync failed tenant=%s customer=%s", tenant_id, customer_id)
        if isinstance(exc, (TimeoutError, OSError, RouterOSAPIError)) and _router_is_agent_linked(tenant):
            payload["mikrotik_bridge_name"] = mikrotik_managed_bridge_name(tenant)
            queued = _queue_router_command_for_tenant(tenant_id, {
                "type": "sync_secrets", "customer_ids": [customer_id], "script": _customer_secret_script(payload),
            }, tenant)
            command_id = getattr(queued, "data", {}).get("command_id")
            logger.info("Customer update sync fell back to router agent tenant=%s customer=%s command=%s error=%s", tenant_id, customer_id, command_id, exc)
            ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
                "router_sync_status": "queued", "router_sync_error": str(exc)[:500],
                "provisioning_message": f"Direct RouterOS sync failed: {exc}. Update queued for agent sync.",
            })
            if send_credentials:
                send_sms_message(customer.get("phone"), _customer_credentials_sms(customer, tenant), tenant)
            return {"status": "queued"}
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
            "router_sync_status": "failed", "router_sync_error": str(exc)[:500],
        })
        raise


@shared_task(bind=True, max_retries=4, default_retry_delay=30)
def notify_customer_created(self, tenant_id, customer_id):
    """Send customer creation WhatsApp notifications asynchronously."""
    from management.api.v1.views import notify_customer_created as send_created_notification

    tenant_record = Tenant.objects.filter(pk=tenant_id).first()
    customer_record = Customer.objects.filter(tenant_id=tenant_id, pk=customer_id).first()
    if not tenant_record or not customer_record:
        return {"status": "missing_record"}
    tenant = {"id": str(tenant_record.pk), **tenant_record.as_dict()}
    customer = customer_record.as_dict()
    try:
        result = send_created_notification(tenant, customer)
        status = "sent" if result.get("customer_whatsapp", {}).get("sent") else "skipped"
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
            "customer_created_notification_status": status,
            "customer_created_notification_result": result,
            "customer_created_notification_at": iso_now(),
        })
        return result
    except Exception as exc:
        logger.exception("Customer creation notification failed tenant=%s customer=%s", tenant_id, customer_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update({
            "customer_created_notification_status": "failed",
            "customer_created_notification_error": str(exc)[:500],
        })
        raise


@shared_task
def notify_router_offline():
    """Alert each tenant once when a linked MikroTik stops checking in."""
    now = timezone.now()
    threshold = now - timezone.timedelta(minutes=10)
    alerted = 0
    recovered = 0
    for tenant in list_children("tenants"):
        tenant_id = tenant.get("id")
        if not tenant_id:
            continue
        linked = bool(
            tenant.get("mikrotik_last_seen_at")
            or tenant.get("mikrotik_router_snapshot")
            or tenant.get("mikrotik_provisioning_status") in {"script_downloaded", "completed"}
        )
        if not linked:
            continue
        last_seen = parse_datetime(str(tenant.get("mikrotik_last_seen_at") or ""))
        if last_seen and timezone.is_naive(last_seen):
            last_seen = timezone.make_aware(last_seen, timezone.get_current_timezone())
        offline = not last_seen or last_seen <= threshold
        challenge_path = f"tenants/{tenant_id}"
        if not offline:
            if tenant.get("router_offline_notified_at"):
                ref(challenge_path).update({"router_offline_notified_at": "", "router_recovered_at": iso_now()})
                recovered += 1
            continue
        if tenant.get("router_offline_notified_at"):
            continue
        phone = normalize_phone(tenant.get("phone") or tenant.get("support_phone"))
        if not phone:
            continue
        last_seen_text = last_seen.isoformat() if last_seen else "never"
        message = (
            f"{tenant.get('business_name') or 'Expressnet'} alert: your linked MikroTik router appears offline. "
            f"Last check-in: {last_seen_text}. Please check power and internet connectivity."
        )
        results = []
        whatsapp = send_whatsapp_message(phone, message, tenant)
        if whatsapp.get("sent"):
            results.append("whatsapp")
        sms = send_sms_message(phone, message, tenant)
        if sms.get("sent"):
            results.append("sms")
        if results:
            ref(challenge_path).update({"router_offline_notified_at": iso_now(), "router_offline_notification_channels": results})
            alerted += 1
    return {"alerted": alerted, "recovered": recovered}
