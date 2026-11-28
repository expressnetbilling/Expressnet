import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Customer, InternetPackage, Payment, Tenant, TenantSubscription
from .services import iso_now, list_children, normalize_phone, ref, send_sms_message, send_whatsapp_message, set_customer_enabled, upsert_customer_access, write_audit_log

logger = logging.getLogger(__name__)

"""

"""


@shared_task(bind=True, max_retries=5, default_retry_delay=15)
def activate_paid_payment(self, tenant_id, payment_id):
    """Provision access after a provider has confirmed a payment.

    Provider callbacks must be acknowledged quickly.  RouterOS, RADIUS and
    notification calls can be slow or temporarily unavailable, so doing them
    in the callback process caused successful payments to time out and be
    retried by the provider.  This task is intentionally idempotent: the
    payment record remains the source of truth and ``activate_paid_access``
    can safely be run again after a transient failure.
    """
    from management.api.v1.views import activate_paid_access

    with transaction.atomic():
        record = Payment.objects.select_for_update().filter(tenant_id=tenant_id, pk=payment_id).first()
        if not record:
            return {"status": "missing_record"}
        payment = record.as_dict()
        if payment.get("status") != "success":
            return {"status": "not_ready"}
        access_status = str(payment.get("access_status") or "").lower()
        if access_status in {"active", "radius_ready"}:
            return {"status": access_status}
        started_at = parse_datetime(str(payment.get("activation_started_at") or ""))
        if started_at and timezone.is_naive(started_at):
            started_at = timezone.make_aware(started_at, timezone.get_current_timezone())
        if access_status == "activation_processing" and started_at and started_at > timezone.now() - timedelta(seconds=45):
            return {"status": "already_processing"}
        record.apply_data({
            "access_status": "activation_processing",
            "access_error": "",
            "activation_started_at": iso_now(),
        })
        record.save()
        payment = record.as_dict()

    tenant = ref(f"tenants/{tenant_id}").get() or {}
    try:
        access = activate_paid_access(
            {"id": str(tenant_id), **tenant},
            str(payment_id),
            payment,
            payment.get("phone"),
            payment.get("payment_code") or payment.get("daraja_receipt_number") or payment_id,
        )
        return {"status": "activated", "access": access}
    except Exception as exc:
        logger.exception("Paid access activation failed tenant=%s payment=%s", tenant_id, payment_id)
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
            "access_status": "activation_pending",
            "access_error": str(exc)[:500],
            "activation_last_failed_at": iso_now(),
        })
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise


@shared_task
def request_tenant_settlement(tenant_id, payment_id):
    """Request one queued B2C/B2B settlement outside the payment callback.

    A queued record is claimed before calling Daraja so duplicate callbacks or
    workers cannot submit the same settlement twice.  Ambiguous provider
    failures are left for reconciliation instead of being blindly retried.
    """
    from management.services.billing import (
        initiate_daraja_b2b_settlement,
        initiate_daraja_b2c,
        tenant_settlement_daraja_config,
    )
    import secrets

    payment = ref(f"tenants/{tenant_id}/payments/{payment_id}").get()
    if not payment or payment.get("status") != "success":
        return {"status": "not_ready"}
    if str(payment.get("tenant_settlement_status") or "") != "queued":
        return {"status": payment.get("tenant_settlement_status") or "not_queued"}

    provider = str(payment.get("tenant_settlement_provider") or "")
    destination_type = str(payment.get("tenant_settlement_destination_type") or "")
    payout = payment.get("tenant_payout") or {}
    recipient = (
        payout.get("payout_phone") if provider == "daraja_b2c"
        else payout.get("daraja_settlement_till_number") if destination_type == "till"
        else payout.get("bank_daraja_shortcode")
    )
    amount = float(payment.get("tenant_net_amount") or 0)
    if provider not in {"daraja_b2c", "daraja_b2b"} or not recipient or amount <= 0:
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
            "tenant_settlement_status": "request_failed",
            "tenant_settlement_error": "Settlement destination or amount is invalid.",
            "tenant_settlement_failed_at": iso_now(),
        })
        return {"status": "invalid"}

    originator_id = str(payment.get("tenant_settlement_originator_conversation_id") or f"SET{secrets.token_hex(8).upper()}")[:20]
    claimed_at = iso_now()
    # ``ref`` is backed by the SQL ledger, but use an explicit row lock to
    # make the queued -> initiating transition atomic across workers.
    try:
        with transaction.atomic():
            record = Payment.objects.select_for_update().filter(tenant_id=tenant_id, pk=payment_id).first()
            if record:
                current = record.as_dict()
                if str(current.get("tenant_settlement_status") or "") != "queued":
                    return {"status": current.get("tenant_settlement_status") or "not_queued"}
                record.apply_data({
                    "tenant_settlement_status": "initiating",
                    "tenant_settlement_provider": provider,
                    "tenant_settlement_originator_conversation_id": originator_id,
                    "tenant_settlement_started_at": claimed_at,
                })
                record.save()
    except Exception:
        logger.exception("Could not claim tenant settlement tenant=%s payment=%s", tenant_id, payment_id)
        raise
    ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
        "tenant_settlement_status": "initiating",
        "tenant_settlement_provider": provider,
        "tenant_settlement_originator_conversation_id": originator_id,
        "tenant_settlement_started_at": claimed_at,
    })

    tenant = ref(f"tenants/{tenant_id}").get() or {}
    try:
        if provider == "daraja_b2c":
            response = initiate_daraja_b2c(
                {"id": str(tenant_id), **tenant}, payment_id, amount, recipient,
                remarks=f"{tenant.get('business_name') or tenant_id} internet payment",
                originator_id=originator_id,
            )
        else:
            response = initiate_daraja_b2b_settlement(
                tenant_settlement_daraja_config({"id": str(tenant_id), **tenant}),
                payment_id, amount, destination_type, recipient,
                payout.get("bank_account_number"),
                remarks=f"{tenant.get('business_name') or tenant_id} settlement",
                originator_id=originator_id,
            )
        update = {
            "tenant_settlement_status": "requested",
            "tenant_settlement_requested_at": iso_now(),
            "tenant_settlement_recipient": recipient,
            "tenant_settlement_conversation_id": response.get("ConversationID"),
            "tenant_settlement_originator_conversation_id": response.get("OriginatorConversationID") or originator_id,
            "tenant_settlement_response_code": response.get("ResponseCode"),
            "tenant_settlement_response_description": response.get("ResponseDescription"),
        }
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update(update)
        ref(f"tenants/{tenant_id}").update({
            "settlement_status": "requested",
            "settlement_last_requested_amount": amount,
            "settlement_last_requested_at": update["tenant_settlement_requested_at"],
        })
        return {"status": "requested", "conversation_id": update["tenant_settlement_conversation_id"]}
    except Exception as exc:
        logger.exception("Tenant settlement request failed tenant=%s payment=%s", tenant_id, payment_id)
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
            "tenant_settlement_status": "request_failed",
            "tenant_settlement_error": str(getattr(exc, "detail", exc))[:500],
            "tenant_settlement_failed_at": iso_now(),
        })
        ref(f"tenants/{tenant_id}").update({"settlement_status": "request_failed"})
        return {"status": "request_failed"}


@shared_task
def reconcile_pending_payment_work(batch_size=100):
    """Recover work that was accepted while a worker/broker was unavailable."""
    activation_ids = list(
        Payment.objects.filter(status="success", access_status__in=["activation_pending", "activation_failed", "activation_processing"])
        .values_list("tenant_id", "pk")[:batch_size]
    )
    settlement_ids = list(
        Payment.objects.filter(status="success", extra__tenant_settlement_status="queued")
        .values_list("tenant_id", "pk")[:batch_size]
    )
    for tenant_id, payment_id in activation_ids:
        activate_paid_payment.delay(str(tenant_id), str(payment_id))
    for tenant_id, payment_id in settlement_ids:
        request_tenant_settlement.delay(str(tenant_id), str(payment_id))
    return {"activation": len(activation_ids), "settlement": len(settlement_ids)}


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
def expire_customer_access(batch_size=500):
    """Expire only due records, in a bounded batch.

    This task runs every five minutes.  Scanning every tenant and serializing
    every customer made its runtime proportional to the entire installation,
    even when no account had expired.
    """
    now = iso_now()
    count = 0
    due_customers = (
        Customer.objects.select_related("tenant")
        .filter(expiry_date__lte=now)
        .exclude(expiry_date__isnull=True)
        .exclude(expiry_date="")
        .exclude(status="expired")
        .order_by("expiry_date", "id")[:batch_size]
    )
    for customer_record in due_customers:
        tenant = customer_record.tenant.as_dict()
        customer = customer_record.as_dict()
        service_type = customer.get("service_type") or "hotspot"
        username = customer.get("mac_address") if service_type == "tv" else customer.get("username")
        if service_type == "static":
            try:
                upsert_customer_access(tenant, customer, disabled=True)
            except Exception:
                logger.warning("Could not disable expired static customer=%s", customer_record.pk, exc_info=True)
        elif service_type != "pppoe":
            try:
                set_customer_enabled(tenant, username, service_type, False)
            except Exception:
                logger.warning("Could not disable expired customer=%s", customer_record.pk, exc_info=True)
        customer_record.apply_data(
            {
                "status": "expired",
                "auto_reconnect": False,
                "expired_at": now,
            }
        )
        customer_record.save()
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
        packages_by_name = {
            str(package.name or "").strip().lower(): package
            for package in InternetPackage.objects.filter(tenant_id=tenant_id).only("name", "price", "extra")
        }
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
                    package = packages_by_name.get(str(customer.get("package") or "").strip().lower())
                    package_data = package.as_dict() if package else {}
                    amount = package_data.get("amount_payable") or package_data.get("price") or 0
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
