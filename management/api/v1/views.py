import json
import html
import hashlib
import hmac
import logging
import os
import secrets
import ipaddress
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode, urlparse

import jwt
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import close_old_connections, connection, transaction
from django.db.utils import OperationalError
from django.db.models import Case, CharField, Count, Sum, Q, When, Subquery, F, Value
from django.db.models.functions import Substr, TruncMonth, Lower, Trim
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from billing_api.auth import admin_required, tenant_required
from billing_api.models import AdminAuditLog, AdminUser, Customer, InternetPackage, Payment, PaystackWithdrawal, SubscriptionPayment, Tenant, TenantSubscription, Ticket, User
from network.realtime import publish_realtime_event
from core.models import Tenant as SchemaTenant
from billing_api.services import (
    admin_token,
    check_password,
    create_hotspot_profile,
    create_ppp_profile,
    configure_router_port,
    selected_daraja_method,
    selected_collection_provider,
    daraja_is_configured,
    initiate_daraja_payment,
    initiate_paystack_mpesa_stk,
    create_paystack_transfer_recipient,
    get_paystack_balance,
    initiate_paystack_transfer,
    finalize_paystack_transfer,
    verify_paystack_transfer,
    list_paystack_banks,
    tenant_paystack_platform_fee_percent,
    verify_paystack_transaction,
    paystack_signature_valid,
    tenant_payment_collection_config,
    query_daraja_stk_payment,
    tenant_payout_details,
    daraja_b2b_settlement_status,
    make_daraja_callback_token,
    verify_daraja_callback_token,
    make_payment_access_token,
    verify_payment_access_token,
    _build_port_command_script,
    delete_router_customer,
    captive_portal_url,
    ensure_hotspot_captive_portal,
    find_child_by_field,
    has_mikrotik_credentials,
    hash_password,
    hotspot_alogin_redirect_html,
    expressnet_hotspot_file_html,
    hotspot_error_redirect_html,
    hotspot_login_redirect_html,
    hotspot_redirect_html,
    routeros_hotspot_fetch_script,
    initiate_daraja_stk,
    iso_now,
    walled_garden_hosts,
    list_children,
    mikrotik_managed_bridge_name,
    normalize_public_url,
    normalize_phone,
    normalize_rate_limit,
    routeros_duration,
    package_service_type,
    PaymentProviderError,
    ref,
    _rsc_escape,
    _get_jwt_secret,
    router_connect,
    router_interface_status,
    router_items,
    send_sms_message,
    send_whatsapp_message,
    set_customer_enabled,
    tenant_token,
    upsert_customer_access,
    utcnow,
    write_audit_log,
)


@csrf_exempt
@api_view(["GET"])
@tenant_required
def tenant_audit_logs(request):
    tenant_id = str(request.tenant["id"])
    records = AdminAuditLog.objects.filter(
        Q(tenant_id=tenant_id)
        | Q(target_type="tenant", target_id=tenant_id)
        | Q(metadata__tenantId=tenant_id)
    ).order_by("-timestamp")[:500]
    return Response([item.as_dict() for item in records])
from network.api.v1.views import (
    _customer_secret_script,
    _hotspot_captive_file_script,
    _linked_router_from_tenant,
    _package_profile_script,
    _queue_router_command,
    _queue_router_command_for_tenant,
    _router_is_agent_linked,
)

logger = logging.getLogger(__name__)


DEFAULT_SITE = {
    "brand_name": "Expressnet",
    "headline": "Internet billing built for hotspot businesses",
    "subheadline": "Sell packages, collect M-Pesa payments, and activate MikroTik users automatically.",
    "about": "We help hotspot operators manage customers, packages, payments, and access control from one secure platform.",
    "phone": "+254 701396967/+254 729 281669",
    "email": "expressnet.support@gmail.com",
    "location": "Thika , Kenya",
    "address": "Nairobi, Kenya",
    "cta_label": "Register your business",
    "cta_url": "/register",
}
MASKED = "••••••••"
SENSITIVE_FIELDS = {"password", "mikrotik_pass", }
PAYMENT_SETTING_FIELDS = {
    "payment_methods",
    "payment_provider",
    "business_number",
    "payout_phone",
    "bank_account_number",
    "bank_name",
    "bank_code",
    "bank_daraja_shortcode",
    "daraja_settlement_till_number",
    "settlement_destination_type",
    "daraja_consumer_key",
    "daraja_consumer_secret",
    "daraja_shortcode",
    "daraja_passkey",
    "daraja_till_number",
    "daraja_shortcode_type",
    "daraja_environment",
    "payment_customer_email",
}


def sanitize_router_login_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return ""
    if not (address.is_private or address.is_link_local or address.is_loopback):
        return ""
    path = parsed.path or ""
    if path and not path.endswith("/login"):
        return ""
    return raw


def _customer_username_seed(name, phone):
    base = "".join(ch for ch in str(name or "").lower() if ch.isalnum())
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if base:
        return base[:12]
    if digits:
        return f"user{digits[-6:]}"
    return f"user{secrets.token_hex(3)}"


def _generate_customer_username(tenant_id, name, phone):
    seed = _customer_username_seed(name, phone)
    username = seed
    while Customer.objects.annotate(username_lower=Lower("username")).filter(
        tenant_id=tenant_id, username_lower=username.lower()
    ).exists():
        username = f"{seed}{secrets.randbelow(900) + 100}"
    return username


def _generate_customer_password():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def static_ip_network_details(ip_address):
    if not ip_address:
        return {}
    network = ipaddress.ip_network("172.30.0.0/16")
    address = ipaddress.ip_address(ip_address)
    if address not in network:
        return {}
    hosts = network.hosts()
    gateway = str(next(hosts))
    return {
        "subnet_mask": str(network.netmask),
        "gateway": gateway,
        "preferred_dns": gateway,
    }


def static_customer_network():
    return ipaddress.ip_network("172.30.0.0/16")


def static_customer_gateway():
    return str(next(static_customer_network().hosts()))


def is_reserved_static_ip(ip_address):
    return str(ip_address or "").strip() == static_customer_gateway()


def next_static_customer_ip(used_ips):
    reserved = {static_customer_gateway()}
    unavailable = {str(value or "").strip() for value in used_ips if str(value or "").strip()} | reserved
    for address in static_customer_network().hosts():
        address_text = str(address)
        if address_text not in unavailable:
            return address_text
    raise ValueError("No static IP addresses are available")


def _customer_credentials_sms(customer, tenant):
    brand = tenant.get("business_name") or tenant.get("name") or "Expressnet"
    service_type = str(customer.get("service_type") or "internet").upper()
    return (
        f"{brand} {service_type} login details: "
        f"Username: {customer.get('username')}. "
        f"Password: {customer.get('password')}. "
        "Please keep them safe."
    )


def _find_team_member_by_label(tenant, label):
    needle = str(label or "").strip().lower()
    if not needle:
        return None
    members = tenant.get("team_members") if isinstance(tenant, dict) else {}
    if not isinstance(members, dict):
        members = {}
    for member_id, member in members.items():
        values = [
            member_id,
            member.get("name"),
            member.get("email"),
            member.get("phone"),
            member.get("role"),
        ]
        if any(str(value or "").strip().lower() == needle for value in values):
            return {"id": member_id, **member}
    return None


def body(request):
    if hasattr(request, "data"):
        if hasattr(request.data, "dict"):
            return request.data.dict()
        return request.data if isinstance(request.data, dict) else dict(request.data)
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def ok(data=None, status=200):
    return Response(data if data is not None else {}, status=status)


def err(message, status=400):
    return Response({"error": message}, status=status)


def admin_notification_recipients():
    configured = list(getattr(settings, "ADMIN_NOTIFICATION_EMAILS", []))
    stored_admins = [admin.get("email") for admin in list_children("admins") if admin.get("email")]
    django_admins = list(User.objects.filter(is_staff=True, is_active=True).values_list("email", flat=True))
    return sorted({email for email in [*configured, *stored_admins, *django_admins] if email})


def send_system_email(subject, message, recipients):
    recipients = [email for email in recipients if email]
    if not recipients:
        return 0
    try:
        return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
    except Exception:
        return 0


def notify_admins_tenant_signup(tenant_id, tenant):
    default_dashboard_url = f"/{settings.ADMIN_FRONTEND_PATH}/tenants"
    dashboard_url = os.getenv("ADMIN_TENANTS_URL", default_dashboard_url)
    send_system_email(
        "New tenant account pending activation",
        (
            f"A new tenant account is waiting for activation.\n\n"
            f"Business: {tenant.get('business_name')}\n"
            f"Owner: {tenant.get('owner_name')}\n"
            f"Email: {tenant.get('email')}\n"
            f"Phone: {tenant.get('phone')}\n"
            f"Tenant ID: {tenant_id}\n\n"
            f"Review and activate it here: {dashboard_url}"
        ),
        admin_notification_recipients(),
    )


def notify_tenant_activated(tenant):
    send_system_email(
        "Your Billing SaaS account is active",
        (
            f"Hello {tenant.get('owner_name') or tenant.get('business_name')},\n\n"
            f"Your {tenant.get('business_name') or 'Billing SaaS'} account has been activated. "
            "You can now sign in and finish setting up your workspace.\n\n"
            "Login: /login"
        ),
        [tenant.get("email")],
    )


def method(request, *allowed):
    return request.method.upper() in allowed


def parse_page(request):
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(200, max(1, int(request.GET.get("page_size", 50))))
    except (TypeError, ValueError):
        page_size = 50
    return page, page_size


def paginate_items(request, items):
    page, page_size = parse_page(request)
    paginator = Paginator(list(items), page_size)
    current = paginator.get_page(page)
    path = request.path
    next_url = f"{path}?page={current.next_page_number()}&page_size={page_size}" if current.has_next() else None
    prev_url = f"{path}?page={current.previous_page_number()}&page_size={page_size}" if current.has_previous() else None
    return {"results": list(current.object_list), "count": paginator.count, "pages": paginator.num_pages, "next": next_url, "previous": prev_url}


def as_collection_response(request, items):
    if request.GET.get("all") == "1" or request.GET.get("format") == "legacy":
        return ok(list(items))
    return ok(paginate_items(request, items))


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def payment_date(payment):
    return parse_date(payment.get("paid_at") or payment.get("initiated_at") or payment.get("created_at"))


def package_duration_delta(package):
    unit = str((package or {}).get("duration_unit") or "").strip().lower()
    if unit in {"month", "months"}:
        try:
            return timedelta(days=31 * float((package or {}).get("duration_value") or (package or {}).get("duration_months") or 1))
        except (TypeError, ValueError):
            return timedelta(days=31)
    hours = (package or {}).get("duration_hours")
    if hours not in {None, ""}:
        try:
            return timedelta(hours=float(hours))
        except (TypeError, ValueError):
            pass
    if unit in {"hour", "hours"}:
        try:
            return timedelta(hours=float((package or {}).get("duration_value") or (package or {}).get("duration_days") or 1))
        except (TypeError, ValueError):
            return timedelta(hours=1)
    try:
        return timedelta(days=int((package or {}).get("duration_days") or 1))
    except (TypeError, ValueError):
        return timedelta(days=1)


def _add_calendar_months(start, months):
    whole_months = max(1, int(months))
    month_index = start.month - 1 + whole_months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    next_month_index = month if month < 12 else 0
    next_month_year = year if month < 12 else year + 1
    last_day = (datetime(next_month_year, next_month_index + 1, 1) - timedelta(days=1)).day
    return start.replace(year=year, month=month, day=min(start.day, last_day))


def package_expiry_date(start, package):
    unit = str((package or {}).get("duration_unit") or "").strip().lower()
    if unit in {"month", "months"}:
        try:
            return _add_calendar_months(start, float((package or {}).get("duration_value") or (package or {}).get("duration_months") or 1))
        except (TypeError, ValueError):
            return _add_calendar_months(start, 1)
    return start + package_duration_delta(package)


def normalized_package_payload(data, default_service_type="hotspot", include_service_type=True):
    service_type = package_service_type(data or {})
    if service_type not in {"hotspot", "pppoe", "static"}:
        service_type = default_service_type if default_service_type in {"hotspot", "pppoe", "static"} else "hotspot"
    raw_unit = str((data or {}).get("duration_unit") or "").lower()
    if raw_unit.startswith("hour"):
        duration_unit = "hours"
    elif raw_unit.startswith("month"):
        duration_unit = "months"
    else:
        duration_unit = "days"
    if duration_unit == "months":
        duration_value = float((data or {}).get("duration_value") or (data or {}).get("duration_months") or 1)
    elif duration_unit == "hours":
        duration_value = float((data or {}).get("duration_value") or (data or {}).get("duration_hours") or 1)
    else:
        duration_value = float((data or {}).get("duration_value") or (data or {}).get("duration_days") or 1)
    if service_type == "pppoe" and duration_value < 1:
        duration_value = 1
    if duration_unit == "hours":
        duration_days = 1
        duration_hours = duration_value
    elif duration_unit == "months":
        duration_days = int(duration_value * 31)
        duration_hours = duration_days * 24
    else:
        duration_days = int(duration_value)
        duration_hours = duration_value * 24
    payload = {
        "duration_unit": duration_unit,
        "duration_value": duration_value,
        "duration_days": duration_days,
        "duration_hours": duration_hours,
        "duration_months": duration_value if duration_unit == "months" else "",
    }
    if include_service_type:
        payload["service_type"] = service_type
    return payload


def package_is_bundle(package):
    return str((package or {}).get("package_kind") or (package or {}).get("access_model") or "").strip().lower() == "bundle"


def package_data_limit_bytes(package):
    try:
        limit_mb = float((package or {}).get("data_limit_mb") or 0)
    except (TypeError, ValueError):
        return 0
    return int(limit_mb * 1024 * 1024) if limit_mb > 0 else 0


def sync_package_profile(tenant, package):
    service_type = package_service_type(package)
    duration_seconds = None if package_is_bundle(package) else int(package_duration_delta(package).total_seconds())
    if service_type == "pppoe":
        return create_ppp_profile(tenant, package.get("name"), package.get("speed"), duration_seconds)
    if service_type == "static":
        return None
    return create_hotspot_profile(tenant, package.get("name"), package.get("speed"), duration_seconds)


def _package_sync_script_for_request(request, package):
    script = _package_profile_script(package)
    if script and package_service_type(package) == "hotspot":
        script = _hotspot_captive_file_script(
            {"id": request.tenant["id"], **request.tenant},
            public_base_url(request).rstrip("/"),
        ) + script
    return script

#u
def package_duration_label(package):
    unit = str((package or {}).get("duration_unit") or "").strip().lower()
    if unit in {"month", "months"}:
        value = float(package.get("duration_value") or 1)
        return f"{value:g} month{'s' if float(value) != 1 else ''}"
    delta = package_duration_delta(package)
    total_seconds = int(delta.total_seconds())
    if total_seconds < 86400:
        hours = max(1, round(total_seconds / 3600))
        return f"{hours} hour{'s' if hours != 1 else ''}"
    days = max(1, round(total_seconds / 86400))
    return f"{days} day{'s' if days != 1 else ''}"


def normalize_mac(value):
    raw = "".join(ch for ch in str(value or "").upper() if ch in "0123456789ABCDEF")
    if len(raw) != 12:
        return ""
    return ":".join(raw[index : index + 2] for index in range(0, 12, 2))


def format_money(value):
    return float(Decimal(str(value or 0)))


def health_payload():
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = "error"
        checks["dbError"] = f"{exc.__class__.__name__}: {str(exc)[:240]}"
    try:
        import redis
        from django.conf import settings as django_settings
        redis.Redis.from_url(django_settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5).ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = "error"
        checks["redisError"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"
    checks["status"] = "healthy" if checks["db"] == "ok" and checks["redis"] == "ok" else "degraded"
    return checks


def ensure_subscription(tenant, plan="basic"):
    plan_amounts = {"basic": 1500, "pro": 3500, "enterprise": 8000}
    now = timezone.now()
    subscription, _ = TenantSubscription.objects.get_or_create(
        tenant=tenant,
        defaults={
            "plan": plan if plan in plan_amounts else "basic",
            "amount": plan_amounts.get(plan, 1500),
            "started_at": now,
            "expires_at": now + timedelta(days=30),
        },
    )
    return subscription


def subscription_payload(subscription, include_payments=False):
    data = subscription.as_dict()
    if include_payments:
        data["payments"] = [payment.as_dict() for payment in subscription.payments.order_by("-paid_at")]
    return data


def record_subscription_payment(subscription, data, admin_email=""):
    now = timezone.now()
    current_expiry = subscription.expires_at if subscription.expires_at and subscription.expires_at > now else now
    period_start = current_expiry
    period_end = period_start + timedelta(days=subscription.billing_cycle_days)
    payment = SubscriptionPayment.objects.create(
        subscription=subscription,
        amount=Decimal(str(data.get("amount") or subscription.amount or 0)),
        currency=data.get("currency") or subscription.currency,
        method=data.get("method") or "manual",
        reference=data.get("reference") or "",
        notes=data.get("notes") or "",
        period_start=period_start,
        period_end=period_end,
        recorded_by=admin_email or "",
    )
    subscription.last_paid_at = payment.paid_at
    subscription.expires_at = period_end
    subscription.save(update_fields=["last_paid_at", "expires_at", "updated_at"])
    if subscription.tenant.status == "suspended":
        subscription.tenant.status = "active"
        subscription.tenant.save(update_fields=["status", "updated_at"])
    return payment


def react_app(request):
    index = Path(settings.BASE_DIR) / "frontend" / "dist" / "index.html"
    if not index.exists():
        raise Http404("Build the React app first with npm --prefix frontend run build")
    return FileResponse(index.open("rb"), content_type="text/html")


def react_asset(request, asset_path):
    assets_dir = (Path(settings.BASE_DIR) / "frontend" / "dist" / "assets").resolve()
    requested = (assets_dir / asset_path).resolve()
    if assets_dir not in requested.parents or not requested.exists() or not requested.is_file():
        raise Http404("Asset not found")
    content_types = {
        ".css": "text/css",
        ".js": "application/javascript",
        ".map": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }
    return FileResponse(requested.open("rb"), content_type=content_types.get(requested.suffix.lower(), "application/octet-stream"))


def public_base_url(request):
    host = request.get_host()
    if "://" in host:
        host = host.split("://", 1)[1]
    forwarded_proto = (request.META.get("HTTP_X_FORWARDED_PROTO") or request.scheme or "https").split(",")[0].strip()
    request_url = normalize_public_url(f"{forwarded_proto}://{host}")

    candidates = [
        os.getenv("PUBLIC_APP_URL"),
        getattr(settings, "PUBLIC_APP_URL", ""),
        ]
    if request_url and "localhost" not in request_url and "127.0.0.1" not in request_url:
        candidates.insert(0, request_url)
    if not settings.DEBUG:
        candidates = [item for item in candidates if item and "localhost" not in item and "127.0.0.1" not in item]
    configured = next((item for item in candidates if item), "")
    return normalize_public_url(configured or request_url)


def tenant_theme_payload(tenant):
    return {
        "business_name": tenant.get("business_name") or "",
        "owner_name": tenant.get("owner_name") or "",
        "phone": tenant.get("phone") or "",
        "support_email": tenant.get("support_email") or tenant.get("email") or "",
        "theme_color": tenant.get("theme_color") or "#fa8200",
        "font": tenant.get("font") or "Work Sans",
        "dark_mode": bool(tenant.get("dark_mode")),
        "theme_mode": tenant.get("theme_mode") or ("dark" if tenant.get("dark_mode") else "dark"),
        "business_number": tenant.get("business_number") or "",
        "payout_phone": tenant.get("payout_phone") or tenant.get("phone") or "",
        "bank_code": tenant.get("bank_code") or "",
        "bank_name": tenant.get("bank_name") or "",
        "bank_daraja_shortcode": tenant.get("bank_daraja_shortcode") or "",
        "daraja_settlement_till_number": tenant.get("daraja_settlement_till_number") or "",
        "settlement_destination_type": tenant.get("settlement_destination_type") or ("till" if tenant.get("daraja_settlement_till_number") else "bank"),
        "bank_account_number": tenant.get("bank_account_number") or "",
        "payment_methods": [method for method in (tenant.get("payment_methods") if isinstance(tenant.get("payment_methods"), list) else ["daraja_paybill"]) if method != "paystack"] or ["daraja_paybill"],
        "daraja_b2b_settlement_status": daraja_b2b_settlement_status(tenant),
        "has_daraja_consumer_key": bool(tenant.get("daraja_consumer_key")),
        "has_daraja_consumer_secret": bool(tenant.get("daraja_consumer_secret")),
        "daraja_shortcode": tenant.get("daraja_shortcode") or "",
        "has_daraja_passkey": bool(tenant.get("daraja_passkey")),
        "daraja_till_number": tenant.get("daraja_till_number") or "",
        "daraja_shortcode_type": tenant.get("daraja_shortcode_type") or "CustomerPayBillOnline",
        "daraja_environment": tenant.get("daraja_environment") or "production",
        "settlement_status": daraja_b2b_settlement_status(tenant),
        "settlement_pending_amount": float(tenant.get("settlement_pending_amount") or 0),
    }



@csrf_exempt
@api_view(["GET"])
def public_tenant(request, tenant_id):
    tenant = ref(f"tenants/{tenant_id}").get()
    if not tenant:
        return ok({"message": "Tenant not found"}, 404)
    payment_methods = tenant.get("payment_methods") if isinstance(tenant.get("payment_methods"), list) else []
    public_payment_methods = [
        str(method).strip().lower()
        for method in payment_methods
        if str(method).strip().lower() in {"daraja_paybill", "daraja_buygoods"}
    ] or [selected_daraja_method(tenant)]
    return ok({
        "id": tenant_id,
        "business_name": tenant.get("business_name"),
        "phone": tenant.get("phone"),
        "status": tenant.get("status"),
        "logo_url": tenant.get("logo_url") or "",
        "payment_methods": public_payment_methods,
        "collection_provider": "daraja",
    })




def _public_package_payload(pkg):
    amount_payable = float(pkg.get("amount_payable") or pkg.get("price") or 0)
    return {
        **{key: pkg.get(key) for key in ["id", "name", "speed", "duration_days", "duration_unit", "duration_value", "duration_hours", "price", "service_type"]},
        "amount_payable": amount_payable,
        "service_type": package_service_type(pkg),
        "duration_label": package_duration_label(pkg),
    }


def _public_packages_for_tenant(tenant_id, requested_service=""):
    return [
        _public_package_payload(pkg)
        for pkg in list_children(f"tenants/{tenant_id}/packages")
        if pkg.get("is_active") is not False and (requested_service not in {"hotspot", "pppoe"} or package_service_type(pkg) == requested_service)
    ]


def _captive_packages(tenant_id):
    hotspot_packages = _public_packages_for_tenant(tenant_id, "hotspot")
    if hotspot_packages:
        return hotspot_packages
    return _public_packages_for_tenant(tenant_id)



@csrf_exempt
@api_view(["POST"])
def _public_pay_impl(request, tenant_id):
    data = body(request)
    if not data.get("package_id") or not data.get("phone"):
        return ok({"message": "Package and phone number are required"}, 400)
    tenant_data = ref(f"tenants/{tenant_id}").get()
    if not tenant_data:
        return ok({"message": "Tenant not found"}, 404)
    if tenant_data.get("status") == "suspended":
        return ok({"message": "Tenant is not accepting payments"}, 403)
    pkg = ref(f"tenants/{tenant_id}/packages/{data['package_id']}").get()
    if not pkg or pkg.get("is_active") is False:
        return ok({"message": "Package not found"}, 404)
    tenant = {"id": tenant_id, **tenant_data}
    phone = normalize_phone(data["phone"])
    router_client_ip = str(data.get("ip") or data.get("client_ip") or "").strip()
    router_ip = str(data.get("router_ip") or "").strip()
    router_mac = str(data.get("mac") or data.get("router_mac") or "").strip()
    router_client_mac = normalize_mac(router_mac)
    link_login = sanitize_router_login_url(data.get("link_login") or data.get("link-login"))
    dst = str(data.get("dst") or data.get("link-orig") or "").strip()
    service_type = str(data.get("service_type") or "hotspot").strip().lower()
    if service_type not in {"hotspot", "pppoe", "tv"}:
        return ok({"message": "Invalid service type"}, 400)
    package_type = package_service_type(pkg)
    if service_type in {"hotspot", "pppoe"} and service_type != package_type:
        return ok({"message": f"This package is only available for {package_type.upper()} customers"}, 400)
    if service_type == "tv" and package_type != "hotspot":
        return ok({"message": "TV MAC access is only available for hotspot packages"}, 400)
    amount_payable = float(pkg.get("amount_payable") or pkg.get("price") or 0)
    customer = None
    username = ""
    mac_address = router_client_mac if service_type == "hotspot" else ""
    if service_type == "pppoe":
        username = str(data.get("username") or "").strip()
        if username:
            customer_record = Customer.objects.annotate(username_lower=Lower("username")).filter(
                tenant_id=tenant_id, username_lower=username.lower()
            ).first()
            customer = customer_record.as_dict() if customer_record else None
        phone = normalize_phone(data.get("phone") or (customer or {}).get("phone"))
    elif service_type == "tv":
        mac_address = normalize_mac(data.get("mac_address"))
        if not mac_address:
            return ok({"message": "Enter a valid TV MAC address"}, 400)
    access_username = mac_address if service_type == "tv" else ((customer or {}).get("username") or username or to_access_username(phone))
    pending_access_password = str((customer or {}).get("password") or secrets.token_hex(3).upper())
    daraja_method = selected_daraja_method(tenant, data.get("payment_method"))
    try:
        daraja_config = tenant_payment_collection_config(tenant, daraja_method)
    except PaymentProviderError as exc:
        return ok({"success": False, "message": exc.public_message}, exc.status_code)
    daraja_source = "platform"
    collection_account = "platform_daraja"
    # Avoid sending duplicate STK requests when a captive browser resubmits a
    # payment while the earlier prompt is still awaiting the customer's PIN.
    pending_cutoff = timezone.now() - timedelta(minutes=5)
    existing_payment = None
    for candidate in reversed(list_children(f"tenants/{tenant_id}/payments")):
        if str(candidate.get("status") or "").lower() != "pending":
            continue
        if str(candidate.get("provider") or "mpesa").lower() != "mpesa":
            continue
        if str(candidate.get("package_id") or "") != str(data["package_id"]):
            continue
        if str(candidate.get("service_type") or "hotspot").lower() != service_type:
            continue
        if normalize_phone(candidate.get("phone")) != phone:
            continue
        if service_type == "hotspot" and router_client_mac and normalize_mac(candidate.get("router_client_mac") or candidate.get("router_mac")) != router_client_mac:
            continue
        if service_type == "pppoe" and access_username and str(candidate.get("username") or "") != access_username:
            continue
        if not candidate.get("daraja_checkout_request_id"):
            continue
        try:
            initiated_at = datetime.fromisoformat(str(candidate.get("initiated_at") or "").replace("Z", "+00:00"))
            if timezone.is_naive(initiated_at):
                initiated_at = timezone.make_aware(initiated_at, timezone.get_current_timezone())
        except (TypeError, ValueError):
            continue
        if initiated_at >= pending_cutoff:
            existing_payment = candidate
            break
    if existing_payment:
        payment_id = str(existing_payment.get("id") or "")
        access_token = str(existing_payment.get("access_verify_token") or make_payment_access_token(tenant_id, payment_id))
        if payment_id and not existing_payment.get("access_verify_token"):
            ref(f"tenants/{tenant_id}/payments/{payment_id}").update({"access_verify_token": access_token})
        logger.info("Reusing pending public M-Pesa prompt tenant=%s payment=%s", tenant_id, payment_id)
        return ok({
            "success": True,
            "status": "pending",
            "message": "An M-Pesa prompt is already waiting on this phone. Enter your PIN; do not submit another payment.",
            "paymentId": payment_id,
            "verifyToken": access_token,
            "provider": "mpesa",
            "checkoutRequestId": existing_payment.get("daraja_checkout_request_id"),
        }, 202)
    payment_ref = ref(f"tenants/{tenant_id}/payments").push(
        {
            "customer_id": customer.get("id") if customer else None,
            "customer_name": customer.get("name") if customer else None,
            "package_id": data["package_id"],
            "package_name": pkg.get("name"),
            "amount": amount_payable,
            "amount_payable": amount_payable,
            "payment_code": None,
            "phone": phone,
            "status": "pending",
            "paid_at": None,
            "initiated_at": iso_now(),
            "service_type": service_type,
            "username": access_username,
            "pending_access_password": pending_access_password,
            "mac_address": mac_address,
            "router_ip": router_ip,
            "router_client_ip": router_client_ip,
            "router_client_mac": router_client_mac,
            "router_mac": router_mac,
            "link_login": link_login,
            "dst": dst,
            "source": "customer_portal",
            "provider": "mpesa",
            "payment_method": daraja_method,
            "collection_account": collection_account,
            "daraja_credential_source": daraja_source,
            "tenant_settlement_status": "not_required" if collection_account == "tenant_daraja" else "pending_payment",
            "tenant_payout": tenant_payout_details(tenant),
        }
    )
    try:
        checkout = initiate_daraja_payment(
            daraja_config,
            payment_ref.key,
            amount_payable,
            phone=phone,
            description=f"{pkg.get('name')} internet package",
            metadata={
                "package_id": data["package_id"],
                "package_name": pkg.get("name"),
                "service_type": service_type,
                "username": access_username,
                "pending_access_password": pending_access_password,
                "mac_address": mac_address,
                "router_ip": router_ip,
                "router_client_ip": router_client_ip,
                "router_client_mac": router_client_mac,
                "router_mac": router_mac,
                "link_login": link_login,
                "dst": dst,
            },
            payment_method=daraja_method,
        )
        payment_ref.update({"daraja_checkout_request_id": checkout.get("checkout_request_id"), "daraja_merchant_request_id": checkout.get("merchant_request_id"), "daraja_callback_url": checkout.get("callback_url"), "checkout_requested_at": iso_now()})
        access_token = make_payment_access_token(tenant_id, payment_ref.key)
        payment_ref.update({"access_verify_token": access_token})
        return ok({
            "success": True,
            "message": checkout.get("customer_message") or "Check your phone and enter your M-Pesa PIN to complete payment.",
            "paymentId": payment_ref.key,
            "verifyToken": access_token,
            "provider": "mpesa",
            "checkoutRequestId": checkout.get("checkout_request_id"),
        }, 201)
    except PaymentProviderError as exc:
        logger.warning(
            "Daraja payment provider error for tenant=%s payment=%s detail=%s",
            tenant_id,
            payment_ref.key,
            exc.detail,
        )
        payment_ref.update({"status": "failed", "failed_at": iso_now(), "callback_result_desc": exc.detail})
        return ok({"success": False, "message": "We could not start your payment just now. Please check your M-Pesa number and try again. If the problem continues, contact the service provider.", "paymentId": payment_ref.key}, exc.status_code)
    except Exception as exc:
        logger.exception(
            "Unexpected Daraja payment initiation error for tenant=%s payment=%s",
            tenant_id,
            payment_ref.key,
        )
        payment_ref.update({"status": "failed", "failed_at": iso_now(), "callback_result_desc": str(exc)})
        return ok({"success": False, "message": "M-Pesa payment could not be started. Please confirm the phone number and try again. If it continues, contact support.", "paymentId": payment_ref.key}, 503)


def _public_paystack_impl(request, tenant_id, tenant, pkg, data, phone, service_type, customer, access_username, pending_access_password, mac_address, router_ip, router_client_ip, router_client_mac, router_mac, link_login, dst, amount_payable):
    if str(os.getenv("PAYSTACK_MANUAL_PAYOUTS_ENABLED", "false")).strip().lower() not in {"1", "true", "yes", "on"}:
        # Checkout is Daraja-first. If an old portal/browser still requests
        # Paystack, continue with the current M-Pesa checkout rather than
        # showing a dead-end error page to the customer.
        logger.info("Paystack checkout request redirected to M-Pesa tenant=%s", tenant_id)
        return _public_pay_impl(request, tenant_id)
    reference = f"EN-{tenant_id}-{secrets.token_urlsafe(14)}".replace("_", "-")
    currency = str(os.getenv("PAYSTACK_CURRENCY") or ((ref("site_settings").get() or {}).get("paystack_currency")) or "KES").upper()
    platform_fee_percent = tenant_paystack_platform_fee_percent()
    payment_ref = ref(f"tenants/{tenant_id}/payments").push({
        "customer_id": customer.get("id") if customer else None,
        "customer_name": customer.get("name") if customer else None,
        "package_id": data["package_id"], "package_name": pkg.get("name"),
        "amount": amount_payable, "amount_payable": amount_payable,
        "payment_code": None, "phone": phone, "status": "pending", "paid_at": None,
        "initiated_at": iso_now(), "service_type": service_type, "username": access_username,
        "pending_access_password": pending_access_password, "mac_address": mac_address,
        "router_ip": router_ip, "router_client_ip": router_client_ip, "router_client_mac": router_client_mac,
        "router_mac": router_mac, "link_login": link_login, "dst": dst, "source": "customer_portal",
        "provider": "paystack", "payment_method": "paystack", "currency": currency,
        "payout_model": "pooled", "platform_fee_percent": platform_fee_percent,
        "collection_account": "platform_paystack", "tenant_settlement_status": "pending_withdrawal",
        "tenant_id": str(tenant_id),
        "paystack_reference": reference,
    })
    access_token = make_payment_access_token(tenant_id, payment_ref.key)
    payment_ref.update({"access_verify_token": access_token})
    _upsert_sql_paystack_payment(tenant_id, payment_ref.key, payment_ref.get())
    charge_attempted = False
    try:
        email = str(data.get("email") or (customer or {}).get("email") or tenant.get("payment_customer_email") or tenant.get("support_email") or tenant.get("email") or "").strip()
        if "@" not in email:
            # The Paystack Charge API requires an email; the captive flow only
            # asks the customer for their phone number.
            email_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:20]
            email = f"checkout-{email_hash}@payments.invalid"
        metadata = {"kind": "internet_payment", "tenant_id": str(tenant_id), "payment_id": str(payment_ref.key)}
        charge_attempted = True
        charge = initiate_paystack_mpesa_stk(email=email, amount=amount_payable, phone=phone, reference=reference, currency=currency, metadata=metadata)
        payment_ref.update({"paystack_reference": charge.get("reference") or reference, "paystack_charge_status": charge.get("status") or "", "paystack_display_text": charge.get("display_text") or "", "collection_account": "platform_paystack", "tenant_settlement_status": "pending_withdrawal", "payment_method": "paystack_mpesa_stk", "customer_message": charge.get("display_text") or "Approve the M-Pesa prompt on your phone to complete payment."})
        _upsert_sql_paystack_payment(tenant_id, payment_ref.key, payment_ref.get())
        return ok({"success": True, "message": charge.get("display_text") or "Approve the M-Pesa payment prompt on your phone.", "paymentId": payment_ref.key, "verifyToken": access_token, "provider": "paystack", "paymentMethod": "mpesa_stk", "reference": charge.get("reference") or reference}, 201)
    except PaymentProviderError as exc:
        if exc.status_code == 202:
            payment_ref.update({"paystack_charge_status": "initiation_unknown", "customer_message": exc.public_message})
            _upsert_sql_paystack_payment(tenant_id, payment_ref.key, payment_ref.get())
            return ok({"success": True, "status": "pending", "message": exc.public_message, "paymentId": payment_ref.key, "verifyToken": access_token, "provider": "paystack", "paymentMethod": "mpesa_stk", "reference": reference}, 202)
        payment_ref.update({"status": "failed", "failed_at": iso_now(), "callback_result_desc": exc.detail})
        _upsert_sql_paystack_payment(tenant_id, payment_ref.key, payment_ref.get())
        return ok({"success": False, "message": exc.public_message, "paymentId": payment_ref.key}, exc.status_code)
    except Exception as exc:
        logger.exception("Paystack M-Pesa STK initialization failed tenant=%s payment=%s", tenant_id, payment_ref.key)
        if not charge_attempted:
            payment_ref.update({"status": "failed", "failed_at": iso_now(), "callback_result_desc": str(exc)})
            _upsert_sql_paystack_payment(tenant_id, payment_ref.key, payment_ref.get())
            return ok({"success": False, "message": "M-Pesa payment could not be started. Please try again.", "paymentId": payment_ref.key}, 502)
        payment_ref.update({"paystack_charge_status": "initiation_unknown", "customer_message": "Payment prompt status is being checked. Do not start another payment yet."})
        _upsert_sql_paystack_payment(tenant_id, payment_ref.key, payment_ref.get())
        return ok({"success": True, "status": "pending", "message": payment_ref.get().get("customer_message"), "paymentId": payment_ref.key, "verifyToken": access_token, "provider": "paystack", "paymentMethod": "mpesa_stk", "reference": reference}, 202)


@csrf_exempt
@api_view(["POST"])
def public_pay(request, tenant_id):
    """Keep every public checkout failure as a useful API response."""
    try:
        return _public_pay_impl(request, tenant_id)
    except PaymentProviderError as exc:
        return ok({"success": False, "message": exc.public_message}, exc.status_code)
    except Exception:
        logger.exception("Unexpected public payment initialization failure tenant=%s", tenant_id)
        return ok({"success": False, "message": "M-Pesa payment could not be started. Please confirm the phone number and try again. If it continues, contact support."}, 503)




def _activate_paid_access_from_portal(tenant_id, payment_id):
    """Activate one confirmed payment during a customer portal verification.

    Celery remains responsible for normal callback activation and notifications.
    This deliberately small fallback handles the case where the broker accepted
    the task but a worker has not started yet.  The processing state is claimed
    transactionally so repeated captive-portal polls cannot create duplicate
    RouterOS users or agent commands.
    """
    payment_path = f"tenants/{tenant_id}/payments/{payment_id}"
    fallback_payment = ref(payment_path).get() or {}
    if fallback_payment.get("status") != "success":
        return fallback_payment

    with transaction.atomic():
        record = Payment.objects.select_for_update().filter(tenant_id=tenant_id, pk=_numeric_pk(payment_id)).first()
        payment = record.as_dict() if record else fallback_payment
        if payment.get("status") != "success":
            return payment
        access_status = str(payment.get("access_status") or "").lower()
        if access_status in {"active", "radius_ready", "queued"}:
            return payment
        started_at = parse_datetime(str(payment.get("activation_started_at") or ""))
        if started_at and timezone.is_naive(started_at):
            started_at = timezone.make_aware(started_at, timezone.get_current_timezone())
        # RouterOS API work has short socket timeouts and agent dispatch is
        # immediate. A processing lease longer than this means the worker was
        # restarted or died; a captive portal retry may safely reclaim it.
        if access_status == "activation_processing" and started_at and started_at > timezone.now() - timedelta(seconds=45):
            return payment
        updates = {
            "access_status": "activation_processing",
            "access_error": "",
            "activation_started_at": iso_now(),
            "activation_source": "customer_portal",
        }
        if record:
            record.apply_data(updates)
            record.save()
            payment = record.as_dict()
        else:
            ref(payment_path).update(updates)
            payment = {**payment, **updates}

    tenant = {"id": str(tenant_id), **(ref(f"tenants/{tenant_id}").get() or {})}
    try:
        activate_paid_access(
            tenant,
            str(payment_id),
            payment,
            payment.get("phone"),
            payment.get("payment_code") or payment.get("daraja_receipt_number") or payment_id,
            notify=False,
        )
    except Exception as exc:
        logger.exception("Portal payment activation failed tenant=%s payment=%s", tenant_id, payment_id)
        failure = {
            "access_status": "activation_pending",
            "access_error": str(exc)[:500],
            "activation_last_failed_at": iso_now(),
        }
        ref(payment_path).update(failure)
        publish_realtime_event(
            tenant_id,
            "payment.updated",
            {"payment_id": str(payment_id), "status": "success", **failure},
            payment_id=payment_id,
        )
    return ref(payment_path).get() or payment


@csrf_exempt
@api_view(["GET"])
def public_verify(request, tenant_id):
    requested_payment_id = request.GET.get("payment_id") or request.GET.get("paymentId")
    callback_reference = str(request.GET.get("reference") or request.GET.get("trxref") or "").strip()
    if not requested_payment_id and callback_reference:
        found = Payment.objects.filter(paystack_reference=callback_reference, tenant_id=tenant_id).first()
        if found:
            requested_payment_id = str(found.pk)
        else:
            resolved_payment = _find_paystack_payment(callback_reference)
            if resolved_payment and str(resolved_payment[0]) == str(tenant_id):
                requested_payment_id = str(resolved_payment[1])
    if not requested_payment_id:
        return ok({"message": "Payment ID is required"}, 400)
    payment_id = str(requested_payment_id)
    requested_token = request.GET.get("verify_token") or request.GET.get("verifyToken") or request.GET.get("token")
    payment = ref(f"tenants/{tenant_id}/payments/{payment_id}").get()
    if not payment:
        return ok({"message": "Payment not found"}, 404)
    router_context = {
        "router_ip": request.GET.get("router_ip") or request.GET.get("server-address"),
        "router_client_ip": request.GET.get("ip"),
        "router_client_mac": request.GET.get("mac"),
        "router_mac": request.GET.get("mac"),
        "link_login": request.GET.get("link_login") or request.GET.get("link-login"),
        "dst": request.GET.get("dst") or request.GET.get("link-orig"),
    }
    context_updates = {key: value for key, value in router_context.items() if value and not payment.get(key)}
    if context_updates:
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update(context_updates)
        payment.update(context_updates)
    if payment.get("status") == "success" and str(payment.get("access_status") or "").lower() == "queued":
        synced_customer = Customer.objects.filter(
            tenant_id=tenant_id,
            username__iexact=str(payment.get("access_username") or payment.get("username") or "").strip(),
            status__iexact="active",
            provisioning_status__iexact="provisioned",
        ).first()
        if synced_customer:
            access_updates = {"access_status": "active", "access_error": None}
            ref(f"tenants/{tenant_id}/payments/{payment_id}").update(access_updates)
            payment.update(access_updates)
            sql_payment = Payment.objects.filter(tenant_id=tenant_id, pk=_numeric_pk(payment_id)).first()
            if sql_payment:
                sql_payment.access_status = "active"
                sql_payment.extra = {**(sql_payment.extra or {}), "access_error": None}
                sql_payment.save(update_fields=["access_status", "extra"])
    if payment.get("status") != "success" and payment.get("provider") == "paystack":
        reference = payment.get("paystack_reference")
        if reference:
            try:
                transaction = verify_paystack_transaction(reference)
                if transaction.get("status") == "success":
                    complete_paystack_payment(tenant_id, payment_id, transaction)
                    payment = ref(f"tenants/{tenant_id}/payments/{payment_id}").get() or payment
            except Exception:
                logger.exception("Paystack transaction verification failed tenant=%s payment=%s", tenant_id, payment_id)
    if payment.get("status") != "success":
        checkout_request_id = payment.get("daraja_checkout_request_id") or payment.get("checkout_request_id")
        if checkout_request_id:
            tenant = {"id": tenant_id, **(ref(f"tenants/{tenant_id}").get() or {})}
            try:
                result = query_daraja_stk_payment(tenant, checkout_request_id, payment.get("payment_method"))
                result_code = str(result.get("ResultCode") if result.get("ResultCode") is not None else "")
                if result_code == "0":
                    receipt = payment.get("daraja_receipt_number") or payment.get("payment_code") or checkout_request_id
                    complete_daraja_payment(
                        tenant_id,
                        payment_id,
                        {},
                        payment.get("amount") or payment.get("amount_payable"),
                        receipt,
                        iso_now(),
                        payment.get("phone"),
                    )
                    payment = ref(f"tenants/{tenant_id}/payments/{payment_id}").get() or payment
                elif result_code:
                    ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
                        "status": "failed",
                        "failed_at": iso_now(),
                        "callback_result_code": result_code,
                        "callback_result_desc": result.get("ResultDesc") or "M-Pesa payment was not successful",
                    })
                    return ok({"success": False, "status": "failed", "message": result.get("ResultDesc") or "M-Pesa payment was not successful"}, 400)
            except PaymentProviderError as exc:
                return ok({"success": False, "status": payment.get("status") or "pending", "message": exc.public_message}, 202)
            except Exception:
                logger.exception("Daraja STK verification failed tenant=%s payment=%s checkout=%s", tenant_id, payment_id, checkout_request_id)
        if payment.get("status") != "success":
            return ok({"success": False, "status": payment.get("status") or "pending", "message": "Waiting for M-Pesa confirmation."}, 202)
    radius_customer_ready = True
    tenant_for_access = ref(f"tenants/{tenant_id}").get() or {}
    if tenant_for_access.get("radius_enabled") and payment.get("status") == "success" and payment.get("access_username"):
        radius_customer_ready = Customer.objects.filter(
            tenant_id=tenant_id,
            username__iexact=str(payment.get("access_username") or "").strip(),
            status__iexact="active",
        ).exclude(radius_secret="").exists()
    access_status = str(payment.get("access_status") or "").lower()
    activation_needs_retry = access_status in {"", "pending", "activation_pending", "activation_failed"}
    if payment.get("status") == "success" and (not payment.get("access_username") or not radius_customer_ready or activation_needs_retry or access_status == "activation_processing"):
        # The portal is an active customer request, not a provider callback.
        # Start one bounded activation now so a valid payment is never held
        # hostage by an absent or restarting Celery worker.  Direct RouterOS
        # binary calls apply immediately; agent-only routers receive a single
        # durable command and report ``queued`` until their acknowledgement.
        payment = _activate_paid_access_from_portal(tenant_id, payment_id) or payment
    payment = ref(f"tenants/{tenant_id}/payments/{payment_id}").get() or payment
    access_status = str(payment.get("access_status") or "").lower()
    if payment.get("status") == "success" and access_status not in {"active", "radius_ready"}:
        message = payment.get("access_error") or "Your payment was received, but the router has not activated internet access yet. Please wait or contact the provider."
        return ok({
            "success": False,
            "status": "activation_pending",
            "payment_status": "success",
            "access_status": access_status or "pending",
            "message": message,
            "paymentId": payment_id,
        }, 202)
    if payment.get("status") == "success" and payment.get("provider") == "paystack":
        _upsert_sql_paystack_payment(tenant_id, payment_id, payment)
    can_return_access = verify_payment_access_token(
        tenant_id,
        payment_id,
        requested_token or payment.get("access_verify_token"),
    ) and bool(requested_token)
    payload = {
            "success": payment.get("status") == "success",
            "status": payment.get("status"),
            "package_name": payment.get("package_name"),
            "service_type": payment.get("service_type"),
            "phone": payment.get("phone"),
            "expires_at": payment.get("access_expires_at"),
            "paymentId": payment_id,
        }
    if can_return_access:
        payload.update({
            "username": payment.get("access_username"),
            "password": payment.get("access_password"),
            "mac_address": payment.get("access_mac_address") or payment.get("mac_address"),
            "router_ip": payment.get("router_ip"),
            "router_mac": payment.get("router_mac"),
            "link_login": sanitize_router_login_url(payment.get("link_login")),
            "dst": payment.get("dst"),
        })
    elif payment.get("status") == "success":
        payload["message"] = "Payment verified. Access credentials require the original verification token."
    return ok(payload)


def complete_paystack_payment(tenant_id, payment_id, transaction):
    payment_ref = ref(f"tenants/{tenant_id}/payments/{payment_id}")
    payment = payment_ref.get()
    if not payment:
        return False
    if str(transaction.get("reference") or "") != str(payment.get("paystack_reference") or ""):
        logger.warning("Paystack reference mismatch tenant=%s payment=%s", tenant_id, payment_id)
        return False
    expected = int((Decimal(str(payment.get("amount") or 0)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if int(transaction.get("amount") or 0) != expected or str(transaction.get("currency") or "").upper() != str(payment.get("currency") or "KES").upper():
        logger.warning("Paystack amount/currency mismatch tenant=%s payment=%s", tenant_id, payment_id)
        return False
    if payment.get("status") != "success":
        if transaction.get("status") != "success":
            return False
        code = str(transaction.get("id") or transaction.get("reference") or payment_id)
        paid_at = transaction.get("paid_at") or iso_now()
        payout_fields = {}
        if payment.get("payout_model") == "pooled":
            gross = Decimal(str(transaction.get("amount") or 0)) / Decimal("100")
            processing_fee = Decimal(str(transaction.get("fees") or 0)) / Decimal("100")
            platform_percent = Decimal(str(payment.get("platform_fee_percent") or 0))
            platform_fee = (gross * platform_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tenant_net = max(Decimal("0.00"), gross - processing_fee - platform_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            payout_fields = {
                "payout_model": "pooled",
                "collection_account": "platform_paystack",
                "tenant_settlement_status": "pending_withdrawal",
                "paystack_processing_fee": str(processing_fee),
                "platform_fee_amount": str(platform_fee),
                "tenant_payout_amount": str(tenant_net),
            }
        payment_ref.update({"status": "success", "payment_code": code, "paid_at": paid_at, "paystack_transaction_id": str(transaction.get("id") or ""), "paystack_paid_at": paid_at, "paystack_channel": transaction.get("channel") or "", "customer_message": "Payment confirmed by Paystack", **payout_fields})
        payment = payment_ref.get() or payment
        payment = {**payment, "status": "success", "payment_code": code, "paid_at": paid_at, "paystack_transaction_id": str(transaction.get("id") or ""), "paystack_paid_at": paid_at, "paystack_channel": transaction.get("channel") or "", **payout_fields}
        _upsert_sql_paystack_payment(tenant_id, payment_id, payment)
        _queue_paid_access_activation(tenant_id, payment_id, "Paystack confirmation")
    else:
        _upsert_sql_paystack_payment(tenant_id, payment_id, payment)
    return True


@csrf_exempt
@api_view(["GET"])
def paystack_callback(request):
    reference = str(request.GET.get("reference") or request.GET.get("trxref") or "").strip()
    if not reference:
        return redirect("/")
    try:
        transaction = verify_paystack_transaction(reference)
    except Exception:
        logger.exception("Paystack callback verification failed reference=%s", reference)
        return redirect("/?payment_status=pending")
    if transaction.get("status") != "success":
        return redirect("/?payment_status=failed")
    resolved = _find_paystack_payment(reference)
    if resolved:
        tenant_id, payment_id = resolved
        complete_paystack_payment(tenant_id, payment_id, transaction)
        return redirect(f"/portal/{tenant_id}?payment_id={payment_id}&verify_token={make_payment_access_token(tenant_id, payment_id)}")
    return redirect("/?payment_status=received")


@csrf_exempt
@api_view(["GET"])
def portal_payment_return(request, tenant_id):
    payment_id = str(request.GET.get("payment_id") or "")
    token = str(request.GET.get("verifyToken") or request.GET.get("verify_token") or "")
    if not payment_id:
        return redirect(f"/api/captive/{tenant_id}")
    return redirect(f"/portal/{tenant_id}?payment_id={payment_id}&verify_token={token}")


@csrf_exempt
@api_view(["POST"])
def paystack_webhook(request):
    if not paystack_signature_valid(request.body, request.META.get("HTTP_X_PAYSTACK_SIGNATURE")):
        return ok({"message": "Invalid signature"}, 401)
    try:
        event = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ok({"message": "Invalid payload"}, 400)
    event_name = str(event.get("event") or "")
    if event_name in {"transfer.success", "transfer.failed", "transfer.reversed"}:
        transfer_data = event.get("data") or {}
        transfer_reference = str(transfer_data.get("reference") or "").strip()
        withdrawal = PaystackWithdrawal.objects.filter(reference=transfer_reference).first()
        if withdrawal:
            if event_name == "transfer.success":
                withdrawal.status = "success"
                withdrawal.failure_reason = ""
            else:
                withdrawal.status = "reversed" if event_name == "transfer.reversed" else "failed"
                withdrawal.failure_reason = str(transfer_data.get("reason") or transfer_data.get("message") or event_name.replace("transfer.", "").capitalize())
            withdrawal.transfer_code = str(transfer_data.get("transfer_code") or withdrawal.transfer_code)
            withdrawal.save()
        else:
            logger.info("Paystack transfer webhook has no matching withdrawal reference=%s event=%s", transfer_reference, event_name)
        return ok({"success": True})
    if event_name != "charge.success":
        return ok({"success": True})
    reference = str((event.get("data") or {}).get("reference") or "")
    try:
        transaction = verify_paystack_transaction(reference)
    except Exception:
        logger.exception("Paystack webhook verification failed reference=%s", reference)
        return ok({"message": "Could not verify transaction"}, 502)
    if transaction.get("status") != "success":
        return ok({"success": True, "message": "Transaction not successful"})
    resolved = _find_paystack_payment(reference)
    if resolved:
        tenant_id, payment_id = resolved
        complete_paystack_payment(tenant_id, payment_id, transaction)
        return ok({"success": True})
    logger.warning("No payment found for Paystack reference=%s", reference)
    return ok({"success": True, "message": "No matching payment"})


def _truthy(value):
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


def _pppoe_grace_payload(data, service_type):
    if service_type != "pppoe" or not _truthy(data.get("grace_period_enabled")):
        return {
            "grace_period_enabled": False,
            "grace_period_value": "",
            "grace_period_unit": "",
            "grace_started_at": "",
            "grace_expires_at": "",
            "grace_source": "",
            "expiry_date": None,
        }
    try:
        value = float(data.get("grace_period_value") or 0)
    except (TypeError, ValueError):
        return ok({"message": "Grace period value must be a number"}, 400)
    if value <= 0:
        return ok({"message": "Grace period must be greater than zero"}, 400)
    unit = str(data.get("grace_period_unit") or "days").strip().lower()
    if unit not in {"hours", "days", "weeks", "months"}:
        return ok({"message": "Grace period unit must be hours, days, weeks, or months"}, 400)
    multipliers = {
        "hours": timedelta(hours=value),
        "days": timedelta(days=value),
        "weeks": timedelta(weeks=value),
        "months": timedelta(days=value * 30),
    }
    started_at = utcnow()
    expires_at = started_at + multipliers[unit]
    return {
        "grace_period_enabled": True,
        "grace_period_value": value,
        "grace_period_unit": unit,
        "grace_started_at": started_at.isoformat(),
        "grace_expires_at": expires_at.isoformat(),
        "grace_source": "tenant_free_access",
        "expiry_date": expires_at.isoformat(),
        "status": "active",
        "auto_reconnect": True,
    }


@csrf_exempt
@api_view(["GET", "PATCH", "DELETE"])
@tenant_required
def customers(request, customer_id=None):
    tenant = request.tenant
    if method(request, "GET") and not customer_id:
        queryset = Customer.objects.filter(tenant_id=tenant["id"])
        service_type = str(request.GET.get("service_type") or "").strip().lower()
        status = str(request.GET.get("status") or "").strip().lower()
        search = str(request.GET.get("search") or "").strip()
        ordering = str(request.GET.get("ordering") or "-created_at").strip()
        if service_type in {"pppoe", "hotspot", "static"}:
            queryset = queryset.filter(service_type=service_type)
        if status:
            if status == "inactive":
                queryset = queryset.exclude(status="active")
            elif status == "paused":
                queryset = queryset.filter(status__in=["paused", "suspended", "inactive"])
            elif status == "offline":
                queryset = queryset.filter(status__in=["offline", "expired"])
            elif status == "active":
                queryset = queryset.filter(status="active")
            else:
                queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(phone__icontains=search)
                | Q(username__icontains=search) | Q(package__icontains=search)
                | Q(extra__location__icontains=search) | Q(extra__ip_address__icontains=search)
                | Q(extra__technician__icontains=search)
            )
        ordering_fields = {
            "created_at": ("created_at", "id"), "-created_at": ("-created_at", "-id"),
            "name": ("name", "id"), "-name": ("-name", "-id"),
        }
        queryset = queryset.order_by(*ordering_fields.get(ordering, ("-created_at", "-id")))
        page, page_size = parse_page(request)
        total = queryset.count()
        if request.GET.get("all") == "1" or request.GET.get("format") == "legacy":
            results = []
            for item in queryset:
                payload = item.as_dict(exclude={"password"})
                if not payload.get("password") and payload.get("radius_secret"):
                    payload["password"] = payload["radius_secret"]
                results.append(payload)
            return ok(results)
        start_index = (page - 1) * page_size
        results = []
        for item in queryset[start_index:start_index + page_size]:
            payload = item.as_dict(exclude={"password"})
            if not payload.get("password") and payload.get("radius_secret"):
                payload["password"] = payload["radius_secret"]
            results.append(payload)
        facet_queryset = Customer.objects.filter(tenant_id=tenant["id"])
        if service_type in {"pppoe", "hotspot", "static"}:
            facet_queryset = facet_queryset.filter(service_type=service_type)
        service_counts = {
            item["service_type"] or "pppoe": item["count"]
            for item in facet_queryset
            .values("service_type").annotate(count=Count("id"))
        }
        status_counts = {
            item["status"] or "inactive": item["count"]
            for item in facet_queryset
            .values("status").annotate(count=Count("id"))
        }
        pages = max(1, (total + page_size - 1) // page_size)
        query = request.GET.copy()
        query["page"] = str(page + 1)
        next_url = f"{request.path}?{query.urlencode()}" if page < pages else None
        query["page"] = str(max(1, page - 1))
        prev_url = f"{request.path}?{query.urlencode()}" if page > 1 else None
        return ok({"results": results, "count": total, "overall_count": facet_queryset.count(), "pages": pages, "next": next_url, "previous": prev_url,
                   "service_counts": service_counts, "status_counts": status_counts})
    if method(request, "GET") and customer_id:
        customer = ref(f"tenants/{tenant['id']}/customers/{customer_id}").get()
        if not customer:
            return ok({"message": "Customer not found"}, 404)
        if not customer.get("password") and customer.get("radius_secret"):
            customer["password"] = customer["radius_secret"]
        return ok({"id": customer_id, **customer})
    if method(request, "PATCH") and customer_id:
        customer = ref(f"tenants/{tenant['id']}/customers/{customer_id}").get()
        if not customer:
            return ok({"message": "Customer not found"}, 404)
        data = body(request)
        allowed = [
            "name",
            "phone",
            "location",
            "username",
            "password",
            "amount_payable",
            "package",
            "service_type",
            "status",
            "expiry_date",
            "auto_reconnect",
            "technician",
            "router_serial_number",
            "mikrotik_router_id",
            "grace_period_enabled",
            "grace_period_value",
            "grace_period_unit",
            "grace_started_at",
            "grace_expires_at",
            "grace_source",
        ]
        updates = {field: data[field] for field in allowed if field in data}
        service_type_for_update = str(updates.get("service_type") or customer.get("service_type") or "hotspot").lower()
        adjustment_applied = False
        if service_type_for_update == "hotspot" and any(field in data for field in ["session_adjustment_value", "session_adjustment_unit", "session_adjustment_direction"]):
            raw_value = data.get("session_adjustment_value")
            if raw_value not in (None, ""):
                try:
                    adjustment_value = float(raw_value)
                except (TypeError, ValueError):
                    return ok({"message": "Session adjustment must be a valid number"}, 400)
                if adjustment_value <= 0:
                    return ok({"message": "Session adjustment must be greater than zero"}, 400)
                unit = str(data.get("session_adjustment_unit") or "hours").strip().lower()
                if unit not in {"minutes", "hours", "days"}:
                    return ok({"message": "Session adjustment unit must be minutes, hours, or days"}, 400)
                direction = str(data.get("session_adjustment_direction") or "add").strip().lower()
                if direction not in {"add", "subtract"}:
                    return ok({"message": "Session adjustment direction must be add or subtract"}, 400)
                current_expiry = parse_datetime(str(customer.get("expiry_date") or "")) if customer.get("expiry_date") else None
                if current_expiry and current_expiry.tzinfo is None:
                    current_expiry = timezone.make_aware(current_expiry, timezone.get_current_timezone())
                base_expiry = current_expiry or timezone.now()
                delta_kwargs = {unit: adjustment_value}
                delta = timedelta(**delta_kwargs)
                next_expiry = base_expiry + delta if direction == "add" else base_expiry - delta
                updates["expiry_date"] = next_expiry.isoformat()
                updates["session_adjusted_at"] = iso_now()
                updates["session_adjustment_note"] = f"{direction} {adjustment_value:g} {unit}"
                adjustment_applied = True
        if service_type_for_update == "pppoe" and any(field in data for field in ["grace_period_enabled", "grace_period_value", "grace_period_unit"]):
            grace_payload = _pppoe_grace_payload(data, service_type_for_update)
            if isinstance(grace_payload, Response):
                return grace_payload
            updates.update(grace_payload)
        elif service_type_for_update != "pppoe" and any(field in data for field in ["grace_period_enabled", "grace_period_value", "grace_period_unit"]):
            updates.update({
                "grace_period_enabled": False,
                "grace_period_value": "",
                "grace_period_unit": "",
                "grace_started_at": "",
                "grace_expires_at": "",
                "grace_source": "",
            })
        if not updates:
            return ok({"message": "No customer fields provided"}, 400)
        if "username" in updates:
            duplicate = Customer.objects.annotate(username_lower=Lower("username")).filter(tenant_id=tenant["id"], username_lower=str(updates["username"]).lower()).exclude(pk=customer_id).exists()
            if duplicate:
                return ok({"message": "A customer with this username already exists"}, 409)
        updates["updated_at"] = iso_now()
        ref(f"tenants/{tenant['id']}/customers/{customer_id}").update(updates)
        should_sync_router = any(field in updates for field in ["username", "password", "package", "service_type", "status", "expiry_date"]) or adjustment_applied
        should_send_credentials = "password" in updates or "username" in updates
        sync_queued = False
        if (should_sync_router and service_type_for_update in {"pppoe", "hotspot", "static"}) or should_send_credentials:
            try:
                from billing_api.tasks import sync_customer_access_after_update
                sync_customer_access_after_update.delay(tenant["id"], customer_id, should_send_credentials)
                sync_queued = True
            except Exception:
                logger.exception("Could not enqueue customer update sync tenant=%s customer=%s", tenant["id"], customer_id)
                ref(f"tenants/{tenant['id']}/customers/{customer_id}").update({
                    "router_sync_status": "queue_unavailable",
                    "router_sync_error": "Update sync could not be queued",
                })
        return ok({"success": True, "message": "Customer updated", "sync_queued": sync_queued, "customer": {"id": customer_id, **customer, **updates}})
    if method(request, "DELETE") and customer_id:
        customer = ref(f"tenants/{tenant['id']}/customers/{customer_id}").get()
        if not customer:
            return ok({"message": "Customer not found"}, 404)
        try:
            delete_router_customer(tenant, customer.get("username"), customer.get("service_type") or "pppoe")
        except Exception:
            pass
        ref(f"tenants/{tenant['id']}/customers/{customer_id}").delete()
        return ok({"success": True, "message": "Customer deleted"})
    return ok({"message": "Method not allowed"}, 405)


@csrf_exempt
@api_view(["POST"])
@tenant_required
def customer_add(request):
    data = body(request)
    required = ["name", "phone", "package_name"]
    if any(not data.get(field) for field in required):
        return ok({"message": "Name, phone, and package are required"}, 400)
    service_type = str(data.get("service_type") or "hotspot").strip().lower()
    if service_type not in {"pppoe", "hotspot", "static"}:
        return ok({"message": "Customer service type must be PPPoE, Hotspot, or Static"}, 400)
    data["username"] = str(data.get("username") or "").strip() or _generate_customer_username(request.tenant["id"], data.get("name"), data.get("phone"))
    data["password"] = str(data.get("password") or "").strip() or _generate_customer_password()
    if Customer.objects.annotate(username_lower=Lower("username")).filter(tenant_id=request.tenant["id"], username_lower=data["username"].lower()).exists():
        return ok({"message": "A customer with this username already exists"}, 409)
    customer_status = str(data.get("status") or "active").strip().lower()
    if customer_status not in {"active", "inactive", "paused", "suspended"}:
        return ok({"message": "Customer status must be active, inactive, paused, or suspended"}, 400)
    router_disabled = customer_status != "active"
    provision = data.get("provision_mikrotik")
    if provision is None:
        provision = service_type in {"pppoe", "hotspot"}
    provision = bool(provision)
    if service_type == "static":
        used_ips = set(Customer.objects.filter(tenant_id=request.tenant["id"], service_type="static")
                       .exclude(ip_address="").values_list("ip_address", flat=True))
        requested_ip = str(data.get("ip_address") or "").strip()
        if requested_ip:
            try:
                if ipaddress.ip_address(requested_ip) not in static_customer_network() or requested_ip in used_ips or is_reserved_static_ip(requested_ip):
                    return ok({"message": "Static IP must be unique, belong to 172.30.0.0/16, and not use the gateway 172.30.0.1"}, 400)
            except ValueError:
                return ok({"message": "Enter a valid static IP address"}, 400)
        else:
            try:
                requested_ip = next_static_customer_ip(used_ips)
            except ValueError as exc:
                return ok({"message": str(exc)}, 400)
        data["ip_address"] = requested_ip
        data.update(static_ip_network_details(requested_ip))
        provision = True
    linked_routers = request.tenant.get("linked_routers") or {}
    mikrotik_router_id = str(data.get("mikrotik_router_id") or "").strip()
    if service_type in {"pppoe", "static"} and linked_routers:
        if not mikrotik_router_id:
            return ok({"message": "Select the MikroTik for this customer"}, 400)
        if mikrotik_router_id not in linked_routers:
            return ok({"message": "Selected MikroTik was not found"}, 400)
    if provision and linked_routers:
        if not mikrotik_router_id:
            return ok({"message": "Select the MikroTik router for this customer"}, 400)
        if mikrotik_router_id not in linked_routers:
            return ok({"message": "Selected MikroTik router was not found"}, 400)
    pkg = find_child_by_field(f"tenants/{request.tenant['id']}/packages", "name", data["package_name"])
    if not pkg:
        return ok({"message": f"Package \"{data['package_name']}\" was not found"}, 404)
    amount_payable = float(data.get("amount_payable") or pkg.get("amount_payable") or pkg.get("price") or 0)
    grace_payload = _pppoe_grace_payload(data, service_type)
    if isinstance(grace_payload, Response):
        return grace_payload
    if grace_payload.get("grace_period_enabled"):
        customer_status = "active"
        router_disabled = False
    provisioning_status = "queued" if provision else "not_requested"
    provisioning_message = f"{service_type.upper()} access queued for background provisioning" if provision else None
    if provision:
        if not has_mikrotik_credentials(request.tenant) and not _router_is_agent_linked(request.tenant):
            return ok({"message": "Link a MikroTik router before provisioning customers"}, 400)
    customer_payload = {
            "name": data["name"],
            "phone": data["phone"],
            "location": data.get("location") or "",
            "username": data["username"],
            "password": data["password"],
            "technician": data.get("technician") or "",
            "router_serial_number": data.get("router_serial_number") or "",
            "mikrotik_router_id": mikrotik_router_id,
            "package": data["package_name"],
            "amount_payable": amount_payable,
            "service_type": service_type,
            "ip_address": data.get("ip_address") or "",
            "subnet_mask": data.get("subnet_mask") or "",
            "gateway": data.get("gateway") or "",
            "preferred_dns": data.get("preferred_dns") or "",
            "ip_pool": "Expressnet-static-pool" if service_type == "static" else "",
            "provisioning_status": provisioning_status,
            "provisioning_message": provisioning_message,
            "status": customer_status,
            "expiry_date": grace_payload.get("expiry_date"),
            **grace_payload,
            "auto_reconnect": True,
            "created_at": iso_now(),
        }
    new_ref = ref(f"tenants/{request.tenant['id']}/customers").push(customer_payload)
    notification_result = None
    if provision:
        try:
            from billing_api.tasks import provision_customer_access
            provision_customer_access.delay(request.tenant["id"], new_ref.key)
        except Exception:
            logger.exception("Could not enqueue customer provisioning tenant=%s customer=%s", request.tenant["id"], new_ref.key)
            provisioning_status = "queue_unavailable"
            provisioning_message = "Provisioning could not be queued. Retry provisioning from the customer actions."
            ref(f"tenants/{request.tenant['id']}/customers/{new_ref.key}").update({
                "provisioning_status": provisioning_status, "provisioning_message": provisioning_message,
            })
    if service_type in {"pppoe", "static"}:
        try:
            from billing_api.tasks import notify_customer_created as notify_customer_created_task
            notify_customer_created_task.delay(request.tenant["id"], new_ref.key)
            notification_result = {"queued": True}
        except Exception:
            logger.exception("Could not enqueue customer creation notification tenant=%s customer=%s", request.tenant["id"], new_ref.key)
            ref(f"tenants/{request.tenant['id']}/customers/{new_ref.key}").update({
                "customer_created_notification_status": "queue_unavailable",
                "customer_created_notification_error": "Notification could not be queued",
            })
    # Sync to Postgres + RADIUS if tenant has RADIUS enabled
    if request.tenant.get("radius_enabled") and service_type in {"hotspot", "pppoe"}:
        try:
            from billing_api.radius_provisioning import upsert_pg_customer, sync_radius_customer
            from billing_api.models import Tenant as TenantModel
            tenant_obj = TenantModel.objects.get(pk=request.tenant["id"])
            pg_customer = upsert_pg_customer(tenant_obj, {**data, "service_type": service_type, "status": customer_status})
            if pg_customer:
                sync_radius_customer(tenant_obj, pg_customer)
        except Exception:
            pass
    return ok({"success": True, "message": "Customer added", "customerId": new_ref.key, "notification": notification_result})


def _normalize_permissions(value):
    return value if isinstance(value, dict) else {}


def _team_member_payload(member_id, member):
    return {
        "id": member_id,
        "name": member.get("name") or "",
        "email": member.get("email") or "",
        "phone": member.get("phone") or "",
        "role": member.get("role") or "",
        "status": member.get("status") or "active",
        "permissions": _normalize_permissions(member.get("permissions")),
        "created_at": member.get("created_at") or "",
        "updated_at": member.get("updated_at") or "",
    }


def _tenant_team_members(tenant_id):
    tenant = ref(f"tenants/{tenant_id}").get() or {}
    members = tenant.get("team_members") or {}
    return members if isinstance(members, dict) else {}


def _save_tenant_team_members(tenant_id, members):
    ref(f"tenants/{tenant_id}").update({"team_members": members})


@csrf_exempt
@api_view(["GET"])
@tenant_required
def staff_members(request):
    members = request.tenant.get("team_members") if isinstance(request.tenant, dict) else None
    if not isinstance(members, dict):
        members = _tenant_team_members(request.tenant["id"])
    active_members = [
        _team_member_payload(member_id, member)
        for member_id, member in members.items()
        if member.get("status", "active") == "active"
    ]
    return as_collection_response(request, active_members)


@csrf_exempt
@api_view(["GET", "DELETE"])
@tenant_required
def team_members(request, member_id=None):
    tenant_id = request.tenant["id"]
    members = _tenant_team_members(tenant_id)
    if method(request, "GET") and not member_id:
        return as_collection_response(
            request,
            [_team_member_payload(member_id, member) for member_id, member in members.items()],
        )
    if method(request, "DELETE") and member_id:
        if member_id not in members:
            return ok({"message": "User not found"}, 404)
        members.pop(member_id, None)
        _save_tenant_team_members(tenant_id, members)
        return ok({"success": True, "message": "User removed"})
    return ok({"message": "Method not allowed"}, 405)


@csrf_exempt
@api_view(["POST"])
@tenant_required
def team_invite(request):
    data = body(request)
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").lower().strip()
    phone = str(data.get("phone") or "").strip()
    role = str(data.get("role") or "").strip()
    if not name or not email:
        return ok({"message": "Name and email are required"}, 400)
    password = str(data.get("password") or "").strip()
    if len(password) < 6:
        return ok({"message": "Password must be at least 6 characters"}, 400)
    tenant_id = request.tenant["id"]
    members = _tenant_team_members(tenant_id)
    if any(str(member.get("email") or "").lower() == email for member in members.values()):
        return ok({"message": "A user with this email already exists"}, 409)
    member_id = secrets.token_hex(8)
    member = {
        "name": name,
        "email": email,
        "phone": phone,
        "role": role,
        "password": hash_password(password),
        "permissions": _normalize_permissions(data.get("permissions")),
        "status": "active",
        "created_at": iso_now(),
        "updated_at": iso_now(),
    }
    members[member_id] = member
    _save_tenant_team_members(tenant_id, members)
    return ok({"success": True, "message": "User created", "member": _team_member_payload(member_id, member)})


@csrf_exempt
@api_view(["PATCH"])
@tenant_required
def team_member_permissions(request, member_id):
    tenant_id = request.tenant["id"]
    members = _tenant_team_members(tenant_id)
    member = members.get(member_id)
    if not member:
        return ok({"message": "User not found"}, 404)
    updates = {
        "permissions": _normalize_permissions(body(request).get("permissions")),
        "updated_at": iso_now(),
    }
    members[member_id] = {**member, **updates}
    _save_tenant_team_members(tenant_id, members)
    return ok({"success": True, "message": "Permissions saved", "member": _team_member_payload(member_id, {**member, **updates})})




def _tenant_extra_dict(tenant_id, key):
    tenant = ref(f"tenants/{tenant_id}").get() or {}
    value = tenant.get(key) or {}
    return value if isinstance(value, dict) else {}


def _save_tenant_extra_dict(tenant_id, key, value):
    ref(f"tenants/{tenant_id}").update({key: value})


def _current_member_payload(request):
    member = getattr(request, "tenant_member", None) or {}
    return {
        "id": member.get("id") or request.tenant.get("member_id") or "",
        "name": member.get("name") or request.tenant.get("name") or request.tenant.get("email") or "",
        "email": member.get("email") or request.tenant.get("email") or "",
        "phone": member.get("phone") or request.tenant.get("phone") or "",
        "role": member.get("role") or request.tenant.get("role") or "",
        "status": member.get("status") or "active",
        "created_at": member.get("created_at") or "",
        "updated_at": member.get("updated_at") or "",
        "permissions": _normalize_permissions(member.get("permissions")),
    }


def _task_date(value):
    parsed = parse_date(value)
    if parsed:
        return parsed.date()
    return None


def _is_current_week_task(task):
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    candidate = _task_date(task.get("due_date")) or _task_date(task.get("created_at")) or _task_date(task.get("updated_at"))
    return bool(candidate and week_start <= candidate <= week_end)


def _staff_task_visible(task):
    status = str(task.get("status") or "pending").lower()
    return status in {"pending", "in_progress"} or _is_current_week_task(task)


def _assigned_staff_tasks(tenant_id, member_id):
    return [
        item for item in list_children(f"tenants/{tenant_id}/tickets")
        if str(item.get("assigned_to") or "") == str(member_id) and _staff_task_visible(item)
    ]


@csrf_exempt
@api_view(["GET"])
@tenant_required
def staff_profile(request):
    member = _current_member_payload(request)
    tenant_id = request.tenant["id"]
    tasks = _assigned_staff_tasks(tenant_id, member["id"])
    reports = _tenant_extra_dict(tenant_id, "staff_work_reports")
    requisitions = _tenant_extra_dict(tenant_id, "requisitions")
    my_reports = [report for report in reports.values() if str(report.get("staff_id") or "") == str(member["id"])]
    my_requisitions = [item for item in requisitions.values() if str(item.get("requested_by") or "") == str(member["id"])]
    complete_statuses = {"complete", "completed"}
    completed = sum(1 for task in tasks if str(task.get("status") or "").lower() in complete_statuses)
    return ok(
        {
            "staff": member,
            "tasks": tasks,
            "stats": {
                "assigned_tasks": len(tasks),
                "completed_tasks": completed,
                "pending_tasks": max(len(tasks) - completed, 0),
                "reports_submitted": len(my_reports),
                "requisitions_submitted": len(my_requisitions),
            },
        }
    )


@csrf_exempt
@api_view(["GET", "POST", "PATCH", "DELETE"])
@tenant_required
def requisitions(request, requisition_id=None):
    tenant_id = request.tenant["id"]
    items = _tenant_extra_dict(tenant_id, "requisitions")
    if method(request, "GET") and not requisition_id:
        return as_collection_response(request, [{"id": item_id, **item} for item_id, item in items.items()])
    if method(request, "POST") and not requisition_id:
        data = body(request)
        item_type = str(data.get("type") or data.get("item_type") or "").strip()
        title = str(data.get("title") or data.get("item") or "").strip()
        if not item_type or not title:
            return ok({"message": "Requisition type and item are required"}, 400)
        requester = _current_member_payload(request)
        new_id = secrets.token_hex(8)
        item = {
            "type": item_type,
            "title": title,
            "quantity": str(data.get("quantity") or "1").strip(),
            "reason": str(data.get("reason") or "").strip(),
            "status": str(data.get("status") or "pending").strip(),
            "requested_by": str(data.get("requested_by") or requester["id"]).strip(),
            "requested_by_name": str(data.get("requested_by_name") or requester["name"]).strip(),
            "requested_by_role": str(data.get("requested_by_role") or requester["role"]).strip(),
            "created_at": iso_now(),
            "updated_at": iso_now(),
        }
        items[new_id] = item
        _save_tenant_extra_dict(tenant_id, "requisitions", items)
        return ok({"success": True, "message": "Requisition created", "requisition": {"id": new_id, **item}}, 201)
    if not requisition_id:
        return ok({"message": "Requisition id is required"}, 400)
    item = items.get(requisition_id)
    if not item:
        return ok({"message": "Requisition not found"}, 404)
    if method(request, "PATCH"):
        data = body(request)
        allowed = ["type", "title", "quantity", "reason", "status", "admin_note"]
        updates = {field: str(data[field]).strip() for field in allowed if field in data}
        updates["updated_at"] = iso_now()
        if updates.get("status") in {"approved", "rejected", "issued"}:
            updates["reviewed_at"] = iso_now()
        items[requisition_id] = {**item, **updates}
        _save_tenant_extra_dict(tenant_id, "requisitions", items)
        return ok({"success": True, "message": "Requisition updated", "requisition": {"id": requisition_id, **items[requisition_id]}})
    if method(request, "DELETE"):
        items.pop(requisition_id, None)
        _save_tenant_extra_dict(tenant_id, "requisitions", items)
        return ok({"success": True, "message": "Requisition deleted"})
    return ok({"message": "Method not allowed"}, 405)


@csrf_exempt
@api_view(["GET", "PATCH"])
@tenant_required
def staff_tasks(request, ticket_id=None):
    member = _current_member_payload(request)
    member_id = member["id"]
    tenant_id = request.tenant["id"]
    if method(request, "GET") and not ticket_id:
        tasks = _assigned_staff_tasks(tenant_id, member_id)
        return as_collection_response(request, tasks)
    if not ticket_id:
        return ok({"message": "Task id is required"}, 400)
    ticket = ref(f"tenants/{tenant_id}/tickets/{ticket_id}").get()
    if not ticket or str(ticket.get("assigned_to") or "") != str(member_id):
        return ok({"message": "Assigned task not found"}, 404)
    data = body(request)
    updates = {}
    status = str(data.get("status") or "").strip()
    if status in {"pending", "in_progress", "complete", "bounced"}:
        updates["status"] = status
    if "bounce_reason" in data:
        updates["bounce_reason"] = str(data.get("bounce_reason") or "").strip()
        updates["bounced_at"] = iso_now()
        updates["status"] = "bounced"
    if "work_report" in data:
        updates["work_report"] = str(data.get("work_report") or "").strip()
        updates["reported_at"] = iso_now()
    if "work_image" in data:
        updates["work_image"] = str(data.get("work_image") or "").strip()
        updates["work_image_name"] = str(data.get("work_image_name") or "").strip()
        updates["work_image_uploaded_at"] = iso_now()
    if not updates:
        return ok({"message": "No task updates provided"}, 400)
    updates["updated_at"] = iso_now()
    ref(f"tenants/{tenant_id}/tickets/{ticket_id}").update(updates)
    return ok({"success": True, "message": "Task updated", "task": {"id": ticket_id, **ticket, **updates}})


@csrf_exempt
@api_view(["GET", "POST"])
@tenant_required
def staff_reports(request):
    tenant_id = request.tenant["id"]
    member = _current_member_payload(request)
    reports = _tenant_extra_dict(tenant_id, "staff_work_reports")
    if method(request, "GET"):
        mine = [{"id": report_id, **report} for report_id, report in reports.items() if str(report.get("staff_id") or "") == str(member["id"])]
        return as_collection_response(request, mine)
    data = body(request)
    report = str(data.get("report") or "").strip()
    if not report:
        return ok({"message": "Work report is required"}, 400)
    task_id = str(data.get("task_id") or "").strip()
    report_id = secrets.token_hex(8)
    item = {
        "task_id": task_id,
        "task_title": str(data.get("task_title") or "").strip(),
        "staff_id": member["id"],
        "staff_name": member["name"],
        "staff_role": member["role"],
        "report": report,
        "work_image": str(data.get("work_image") or "").strip(),
        "work_image_name": str(data.get("work_image_name") or "").strip(),
        "created_at": iso_now(),
    }
    reports[report_id] = item
    _save_tenant_extra_dict(tenant_id, "staff_work_reports", reports)
    if task_id:
        updates = {"work_report": report, "reported_at": iso_now(), "updated_at": iso_now()}
        if item["work_image"]:
            updates["work_image"] = item["work_image"]
            updates["work_image_name"] = item["work_image_name"]
            updates["work_image_uploaded_at"] = iso_now()
        ref(f"tenants/{tenant_id}/tickets/{task_id}").update(updates)
    return ok({"success": True, "message": "Work report submitted", "report": {"id": report_id, **item}}, 201)


@csrf_exempt
@api_view(["GET", "POST"])
@tenant_required
def staff_requisitions(request):
    if method(request, "GET"):
        member = _current_member_payload(request)
        items = _tenant_extra_dict(request.tenant["id"], "requisitions")
        mine = [{"id": item_id, **item} for item_id, item in items.items() if str(item.get("requested_by") or "") == str(member["id"])]
        return as_collection_response(request, mine)
    data = body(request)
    item_type = str(data.get("type") or data.get("item_type") or "").strip()
    title = str(data.get("title") or data.get("item") or "").strip()
    quantity = str(data.get("quantity") or "1").strip()
    if not item_type or not title:
        return ok({"message": "Requisition type and item are required"}, 400)
    member = _current_member_payload(request)
    tenant_id = request.tenant["id"]
    items = _tenant_extra_dict(tenant_id, "requisitions")
    new_id = secrets.token_hex(8)
    item = {
        "type": item_type,
        "title": title,
        "quantity": quantity,
        "reason": str(data.get("reason") or "").strip(),
        "status": "pending",
        "requested_by": member["id"],
        "requested_by_name": member["name"],
        "requested_by_role": member["role"],
        "created_at": iso_now(),
        "updated_at": iso_now(),
    }
    items[new_id] = item
    _save_tenant_extra_dict(tenant_id, "requisitions", items)
    return ok({"success": True, "message": "Requisition created", "requisition": {"id": new_id, **item}}, 201)


@csrf_exempt
@api_view(["GET", "POST"])
@tenant_required
def paystack_withdrawals(request):
    tenant_id = request.tenant["id"]
    manual_payouts_enabled = str(os.getenv("PAYSTACK_MANUAL_PAYOUTS_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}
    platform_default = str((ref("site_settings").get() or {}).get("collection_provider") or "daraja")
    if selected_collection_provider(request.tenant, platform_default=platform_default) != "paystack":
        return ok({"message": "Withdrawals are available only when this tenant uses Paystack. Daraja payments are unchanged."}, 400)

    def wallet_summary():
        paystack_payments = Payment.objects.filter(tenant_id=tenant_id, provider="paystack", status="success")
        credits = Decimal("0.00")
        for item in paystack_payments.only("extra"):
            extra = item.extra or {}
            if extra.get("payout_model") == "pooled":
                try:
                    credits += Decimal(str(extra.get("tenant_payout_amount") or "0"))
                except Exception:
                    continue
        reserved = PaystackWithdrawal.objects.filter(
            tenant_id=tenant_id,
            status__in=["initiating", "unknown", "otp", "processing", "success"],
        ).aggregate(total=Sum("amount"), fees=Sum("fee"))
        reserved_total = Decimal(str(reserved.get("total") or 0)) + Decimal(str(reserved.get("fees") or 0))
        return max(Decimal("0.00"), credits - reserved_total).quantize(Decimal("0.01"))

    if method(request, "GET"):
        for pending_item in PaystackWithdrawal.objects.filter(
            tenant_id=tenant_id, status__in=["unknown", "processing"]
        )[:5]:
            try:
                provider_transfer = verify_paystack_transfer(pending_item.reference)
                provider_status = str(provider_transfer.get("status") or "").lower()
                if provider_status == "success":
                    pending_item.status = "success"
                    pending_item.failure_reason = ""
                elif provider_status in {"failed", "reversed"}:
                    pending_item.status = provider_status
                    pending_item.failure_reason = str(provider_transfer.get("reason") or provider_status.capitalize())
                elif provider_status in {"pending", "otp"}:
                    pending_item.status = provider_status
                    pending_item.transfer_code = str(provider_transfer.get("transfer_code") or pending_item.transfer_code)
                pending_item.save()
            except PaymentProviderError as exc:
                logger.info("Paystack withdrawal status refresh deferred id=%s detail=%s", pending_item.pk, exc.detail)
        withdrawals = PaystackWithdrawal.objects.filter(tenant_id=tenant_id)[:20]
        return ok({
            "currency": "KES",
            "available_balance": str(wallet_summary()),
            "withdrawal_fee": str(Decimal(os.getenv("PAYSTACK_WITHDRAWAL_FEE_KES", "80"))),
            "manual_payouts_enabled": manual_payouts_enabled,
            "withdrawals": [item.as_dict() for item in withdrawals],
        })

    if not manual_payouts_enabled:
        return ok({"message": "Paystack manual payouts must be enabled by Paystack and PAYSTACK_MANUAL_PAYOUTS_ENABLED must be set before withdrawals can be submitted."}, 503)

    data = body(request)
    try:
        amount = Decimal(str(data.get("amount") or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return ok({"message": "Enter a valid withdrawal amount."}, 400)
    if amount < Decimal("10.00"):
        return ok({"message": "The minimum Paystack withdrawal is Ksh 10."}, 400)
    payout_method = str(data.get("payout_method") or "").strip().lower()
    if payout_method not in {"bank", "mpesa"}:
        return ok({"message": "Choose a bank account or M-Pesa."}, 400)
    if payout_method == "mpesa" and amount > Decimal("250000.00"):
        return ok({"message": "The maximum single Paystack M-Pesa withdrawal is Ksh 250,000."}, 400)
    tenant = {**request.tenant}
    recipient_name = str(data.get("recipient_name") or tenant.get("owner_name") or tenant.get("business_name") or "").strip()
    if not recipient_name:
        return ok({"message": "Enter the recipient account name."}, 400)
    bank_code = ""
    account_number = ""
    phone = ""
    if payout_method == "bank":
        destination_type = str(data.get("destination_type") or "other_bank").strip().lower()
        if destination_type == "saved_bank":
            bank_code = str(tenant.get("bank_code") or "").strip()
            account_number = str(tenant.get("bank_account_number") or "").strip()
        else:
            bank_code = str(data.get("bank_code") or "").strip()
            account_number = "".join(ch for ch in str(data.get("account_number") or "") if ch.isalnum())
        if not bank_code or len(account_number) < 5:
            return ok({"message": "Select a bank and enter a valid account number."}, 400)
        destination_label = f"Bank ••••{account_number[-4:]}"
    else:
        phone = normalize_phone(data.get("phone") or tenant.get("payout_phone") or "")
        if len(phone) != 12 or not phone.startswith("254"):
            return ok({"message": "Enter a valid Kenyan M-Pesa number."}, 400)
        account_number = phone
        destination_label = f"M-Pesa ••••{phone[-4:]}"

    fee = Decimal(os.getenv("PAYSTACK_WITHDRAWAL_FEE_KES", "80")).quantize(Decimal("0.01"))
    if fee < 0:
        fee = Decimal("0.00")
    try:
        with transaction.atomic():
            tenant_lock = Tenant.objects.select_for_update().get(pk=tenant_id)
            tenant = {**request.tenant, **tenant_lock.as_dict()}
            if PaystackWithdrawal.objects.filter(tenant=tenant_lock, status="unknown").exists():
                return ok({"message": "A previous withdrawal is still being verified. Check its status before submitting another."}, 409)
            available = wallet_summary()
            if amount + fee > available:
                return ok({
                    "message": f"Insufficient Paystack balance. Available: Ksh {available:.2f}; withdrawal plus fee: Ksh {amount + fee:.2f}.",
                    "available_balance": str(available),
                }, 400)
            withdrawal = PaystackWithdrawal.objects.create(
                tenant=tenant_lock,
                amount=amount,
                fee=fee,
                currency="KES",
                payout_method=payout_method,
                destination_label=destination_label,
                reference=f"wd_{secrets.token_hex(16)}",
            )
    except Tenant.DoesNotExist:
        return ok({"message": "Tenant account not found."}, 404)

    try:
        recipient = create_paystack_transfer_recipient(
            payout_method=payout_method,
            name=recipient_name,
            email=str(tenant.get("email") or ""),
            currency="KES",
            bank_code=bank_code,
            account_number=account_number,
        )
        recipient_code = str(recipient.get("recipient_code") or "")
        if not recipient_code:
            raise PaymentProviderError("Paystack did not return a transfer recipient.", "Missing recipient_code", 502)
        withdrawal.recipient_code = recipient_code
        withdrawal.save(update_fields=["recipient_code", "updated_at"])
        required_balance = int(((amount + fee) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        provider_balance = get_paystack_balance("KES")
        if provider_balance < required_balance:
            withdrawal.status = "failed"
            withdrawal.failure_reason = "Paystack balance is not sufficient. Manual payouts must be enabled and funds must be available."
            withdrawal.save(update_fields=["status", "failure_reason", "updated_at"])
            return ok({"message": withdrawal.failure_reason}, 400)
        transfer = initiate_paystack_transfer(
            amount=amount,
            recipient_code=recipient_code,
            reference=withdrawal.reference,
            reason=f"Tenant withdrawal {tenant.get('business_name') or tenant_id}",
            currency="KES",
        )
        transfer_status = str(transfer.get("status") or "pending").lower()
        withdrawal.transfer_code = str(transfer.get("transfer_code") or "")
        withdrawal.status = "otp" if transfer_status == "otp" else "success" if transfer_status == "success" else "processing" if transfer_status in {"pending", "queued"} else "failed"
        if withdrawal.status == "failed":
            withdrawal.failure_reason = str(transfer.get("reason") or transfer.get("message") or "Paystack transfer failed.")
        withdrawal.save()
        return ok({
            "success": withdrawal.status in {"otp", "processing", "success"},
            "otp_required": withdrawal.status == "otp",
            "message": "Paystack OTP is required to continue this withdrawal." if withdrawal.status == "otp" else "Withdrawal submitted to Paystack." if withdrawal.status in {"processing", "success"} else withdrawal.failure_reason,
            "withdrawal": withdrawal.as_dict(),
            "available_balance": str(wallet_summary()),
        }, 202 if withdrawal.status in {"otp", "processing", "success"} else 502)
    except PaymentProviderError as exc:
        # Preserve funds for indeterminate network outcomes until verified.
        if "Check the withdrawal status" in exc.public_message:
            withdrawal.status = "unknown"
        else:
            withdrawal.status = "failed"
            withdrawal.failure_reason = exc.public_message
        withdrawal.save(update_fields=["status", "failure_reason", "updated_at"])
        return ok({"message": exc.public_message, "withdrawal": withdrawal.as_dict()}, 202 if withdrawal.status == "unknown" else exc.status_code)
    except Exception:
        logger.exception("Paystack withdrawal failed tenant=%s withdrawal=%s", tenant_id, withdrawal.pk)
        withdrawal.status = "unknown"
        withdrawal.failure_reason = "Paystack status is being checked. Do not submit this withdrawal again yet."
        withdrawal.save(update_fields=["status", "failure_reason", "updated_at"])
        return ok({"message": withdrawal.failure_reason, "withdrawal": withdrawal.as_dict()}, 202)


@csrf_exempt
@api_view(["POST"])
@tenant_required
def paystack_withdrawal_otp(request, withdrawal_id):
    withdrawal = PaystackWithdrawal.objects.filter(pk=withdrawal_id, tenant_id=request.tenant["id"]).first()
    if not withdrawal:
        return ok({"message": "Withdrawal not found."}, 404)
    if withdrawal.status != "otp" or not withdrawal.transfer_code:
        return ok({"message": "This withdrawal is not waiting for an OTP."}, 400)
    otp = str(body(request).get("otp") or "").strip()
    if not otp:
        return ok({"message": "Enter the Paystack transfer OTP."}, 400)
    try:
        result = finalize_paystack_transfer(transfer_code=withdrawal.transfer_code, otp=otp)
        provider_status = str(result.get("status") or "pending").lower()
        withdrawal.status = "success" if provider_status == "success" else "processing" if provider_status in {"pending", "queued"} else "failed"
        if withdrawal.status == "failed":
            withdrawal.failure_reason = str(result.get("reason") or "Paystack transfer failed.")
        withdrawal.save()
        return ok({"success": withdrawal.status != "failed", "withdrawal": withdrawal.as_dict(), "message": withdrawal.failure_reason or "Withdrawal submitted to Paystack."})
    except PaymentProviderError as exc:
        return ok({"message": exc.public_message}, exc.status_code)


@csrf_exempt
@api_view(["GET", "POST"])
@tenant_required
def payments(request):
    if method(request, "GET"):
        payments_data = list_children(f"tenants/{request.tenant['id']}/payments")
        paystack_refs = {
            str(item.get("paystack_reference") or ""): item
            for item in payments_data
            if item.get("provider") == "paystack" and item.get("paystack_reference")
        }
        sql_paystack_payments = Payment.objects.filter(
            tenant_id=request.tenant["id"], provider="paystack"
        ).order_by("-id")
        for sql_payment in sql_paystack_payments:
            sql_item = sql_payment.as_dict()
            reference = str(sql_item.get("paystack_reference") or "")
            ref_item = paystack_refs.get(reference)
            if ref_item is None:
                payments_data.append(sql_item)
                if reference:
                    paystack_refs[reference] = sql_item
                continue
            for field in (
                "customer_name", "package_name", "service_type", "amount", "payment_code",
                "currency", "phone", "paid_at", "initiated_at", "access_username",
                "access_password", "access_expires_at", "access_status",
            ):
                if ref_item.get(field) in (None, "") and sql_item.get(field) not in (None, ""):
                    ref_item[field] = sql_item[field]
            if sql_item.get("status") == "success":
                ref_item["status"] = "success"
                ref_item["paid_at"] = sql_item.get("paid_at") or ref_item.get("paid_at")
        sql_other_payments = Payment.objects.filter(tenant_id=request.tenant["id"]).exclude(provider="paystack").order_by("-id")
        known_ids = {str(item.get("id") or "") for item in payments_data}
        for sql_payment in sql_other_payments:
            sql_item = sql_payment.as_dict()
            ref_item = next((item for item in payments_data if str(item.get("id") or "") == str(sql_payment.pk)), None)
            if ref_item is None:
                payments_data.append(sql_item)
                known_ids.add(str(sql_payment.pk))
                continue
            for field in ("customer_name", "package_name", "service_type", "amount", "payment_code", "currency", "phone", "paid_at", "initiated_at", "access_username", "access_password", "access_expires_at", "access_status"):
                if ref_item.get(field) in (None, "") and sql_item.get(field) not in (None, ""):
                    ref_item[field] = sql_item[field]
            if sql_item.get("status") == "success":
                ref_item["status"] = "success"
                ref_item["paid_at"] = sql_item.get("paid_at") or ref_item.get("paid_at")
            for field, value in (sql_item.get("extra") or {}).items():
                ref_item.setdefault(field, value)

        # Return persisted SQL records only when the reference ledger contains
        # no payment for this tenant (the payment row remains authoritative).
        if not payments_data:
            payments_data = [item.as_dict() for item in Payment.objects.filter(tenant_id=request.tenant["id"]).order_by("-id")]
        status_filter = request.GET.get("status")
        from_date = parse_date(request.GET.get("from"))
        to_date = parse_date(request.GET.get("to"))
        from_day = from_date.date() if from_date else None
        to_day = to_date.date() if to_date else None
        if status_filter and status_filter != "all":
            payments_data = [item for item in payments_data if item.get("status") == status_filter]
        if from_date or to_date:
            filtered = []
            for item in payments_data:
                current = payment_date(item)
                if not current:
                    continue
                current_day = current.date()
                if from_day and current_day < from_day:
                    continue
                if to_day and current_day > to_day:
                    continue
                filtered.append(item)
            payments_data = filtered
        return as_collection_response(request, payments_data)
    data = body(request)
    if str(data.get("provider") or data.get("payment_provider") or "").strip().lower() == "paystack":
        return ok({"message": "Paystack is unavailable. Use the configured M-Pesa settlement method."}, 410)
    if not data.get("phone"):
        return ok({"message": "Customer phone is required"}, 400)
    phone = normalize_phone(data["phone"])
    daraja_method = selected_daraja_method(request.tenant, data.get("payment_method"))
    try:
        daraja_config = tenant_payment_collection_config(request.tenant, daraja_method)
    except PaymentProviderError as exc:
        return ok({"success": False, "message": exc.public_message}, exc.status_code)
    daraja_source = "platform"
    collection_account = "platform_daraja"
    payment_ref = ref(f"tenants/{request.tenant['id']}/payments").push(
        {
            "customer_id": data.get("customer_id"),
            "customer_name": data.get("customer_name"),
            "package_name": data.get("package_name"),
            "service_type": data.get("service_type") or "pppoe",
            "amount": float(data.get("amount") or 0),
            "payment_code": None,
            "phone": phone,
            "status": "pending",
            "paid_at": None,
            "initiated_at": iso_now(),
            "provider": "mpesa",
            "payment_method": daraja_method,
            "collection_account": collection_account,
            "daraja_credential_source": daraja_source,
            "tenant_settlement_status": "not_required" if collection_account == "tenant_daraja" else "pending_payment",
            "tenant_payout": tenant_payout_details(request.tenant),
        }
    )
    try:
        checkout = initiate_daraja_payment(
            daraja_config,
            payment_ref.key,
            data.get("amount"),
            phone=phone,
            description=f"{data.get('package_name') or 'Internet'} payment",
            metadata={
                "customer_id": data.get("customer_id"),
                "customer_name": data.get("customer_name"),
                "package_name": data.get("package_name"),
                "service_type": data.get("service_type") or "pppoe",
            },
            payment_method=daraja_method,
        )
    except PaymentProviderError as exc:
        payment_ref.update({"status": "failed", "failed_at": iso_now(), "callback_result_desc": exc.detail})
        return ok({"success": False, "message": exc.public_message, "paymentId": payment_ref.key}, exc.status_code)
    payment_ref.update(
        {
            "daraja_checkout_request_id": checkout.get("checkout_request_id"),
            "daraja_merchant_request_id": checkout.get("merchant_request_id"),
            "checkout_requested_at": iso_now(),
        }
    )
    return ok({"success": True, "message": checkout.get("customer_message") or "Check your phone and enter your M-Pesa PIN to complete payment.", "paymentId": payment_ref.key, "provider": "mpesa", "checkoutRequestId": checkout.get("checkout_request_id")})


@csrf_exempt
@api_view(["POST"])
@tenant_required
def payment_mark_paid(request, payment_id):
    payment = ref(f"tenants/{request.tenant['id']}/payments/{payment_id}").get()
    if not payment:
        return ok({"message": "Payment not found"}, 404)
    payment_code = payment.get("payment_code") or f"CASH-{secrets.token_hex(4).upper()}"
    updates = {
        "status": "success",
        "provider": payment.get("provider") or "cash",
        "payment_code": payment_code,
        "paid_at": iso_now(),
        "callback_result_code": "manual",
        "callback_result_desc": "Marked as paid by operator",
    }
    ref(f"tenants/{request.tenant['id']}/payments/{payment_id}").update(updates)
    marked_invoice = mark_customer_invoice_paid(request.tenant["id"], payment.get("customer_id"), {"id": payment_id, **payment, **updates})
    try:
        activate_paid_access(request.tenant, payment_id, {**payment, **updates}, payment.get("phone"), payment_code)
    except Exception as exc:
        ref(f"tenants/{request.tenant['id']}/payments/{payment_id}").update({"access_status": "activation_failed", "callback_result_desc": str(exc)})
        return ok({"success": True, "message": "Payment marked paid, but router activation failed", "activation_error": str(exc)})
    return ok({"success": True, "message": "Payment marked as paid and access activated", "invoice": marked_invoice})


@csrf_exempt
@api_view(["POST"])
@tenant_required
def customer_renew(request, customer_id):
    data = body(request)
    customer = ref(f"tenants/{request.tenant['id']}/customers/{customer_id}").get()
    if not customer:
        return ok({"message": "Customer not found"}, 404)
    package_id = data.get("package_id")
    package = ref(f"tenants/{request.tenant['id']}/packages/{package_id}").get() if package_id else find_child_by_field(f"tenants/{request.tenant['id']}/packages", "name", customer.get("package"))
    if not package or package.get("is_active") is False:
        return ok({"message": "Active package not found"}, 404)
    amount_payable = float(package.get("amount_payable") or package.get("price") or 0)
    payment_ref = ref(f"tenants/{request.tenant['id']}/payments").push(
        {
            "customer_id": customer_id,
            "customer_name": customer.get("name"),
            "package_id": package_id or package.get("id"),
            "package_name": package.get("name"),
            "service_type": customer.get("service_type") or "pppoe",
            "amount": amount_payable,
            "amount_payable": amount_payable,
            "payment_code": f"MANUAL-{secrets.token_hex(4).upper()}",
            "phone": customer.get("phone"),
            "status": "success",
            "paid_at": iso_now(),
            "initiated_at": iso_now(),
            "provider": data.get("provider") or "cash",
            "source": "manual_renewal",
        }
    )
    mark_customer_invoice_paid(request.tenant["id"], customer_id, {"id": payment_ref.key, **payment_ref.instance.as_dict()})
    try:
        activate_paid_access(request.tenant, payment_ref.key, {**payment_ref.instance.as_dict(), "package_name": package.get("name")}, customer.get("phone"), payment_ref.instance.payment_code)
    except Exception as exc:
        payment_ref.update({"access_status": "activation_failed", "callback_result_desc": str(exc)})
        return ok({"success": True, "message": "Renewal saved, but router activation failed", "paymentId": payment_ref.key, "activation_error": str(exc)})
    return ok({"success": True, "message": "Customer renewed and access activated", "paymentId": payment_ref.key})


@csrf_exempt
@api_view(["GET", "POST", "PATCH"])
@tenant_required
def invoices(request, invoice_id=None):
    tenant_id = request.tenant["id"]
    if method(request, "GET") and not invoice_id:
        invoices_data = [{"id": item_id, **item} for item_id, item in _tenant_extra_dict(tenant_id, "invoices").items()]
        status_filter = request.GET.get("status")
        if status_filter and status_filter != "all":
            invoices_data = [item for item in invoices_data if item.get("status") == status_filter]
        return as_collection_response(request, invoices_data)
    if method(request, "POST") and not invoice_id:
        data = body(request)
        invoice = {
            "invoice_number": str(data.get("invoice_number") or _invoice_id()).strip(),
            "customer_id": str(data.get("customer_id") or "").strip(),
            "customer": str(data.get("customer") or data.get("customer_name") or "").strip(),
            "customer_name": str(data.get("customer_name") or data.get("customer") or "").strip(),
            "phone": str(data.get("phone") or "").strip(),
            "item": str(data.get("item") or "Internet subscription").strip(),
            "package_name": str(data.get("package_name") or "").strip(),
            "service_type": str(data.get("service_type") or "").strip(),
            "amount": float(data.get("amount") or 0),
            "due_at": str(data.get("due_at") or iso_now()).strip(),
            "status": str(data.get("status") or "sent").strip(),
            "reason": str(data.get("reason") or "manual").strip(),
            "created_at": iso_now(),
            "updated_at": iso_now(),
        }
        new_id = secrets.token_hex(8)
        invoices_data = _tenant_extra_dict(tenant_id, "invoices")
        invoices_data[new_id] = invoice
        _save_tenant_extra_dict(tenant_id, "invoices", invoices_data)
        return ok({"success": True, "message": "Invoice created", "invoice": {"id": new_id, **invoice}}, 201)
    if not invoice_id:
        return ok({"message": "Invoice id is required"}, 400)
    invoices_data = _tenant_extra_dict(tenant_id, "invoices")
    invoice = invoices_data.get(invoice_id)
    if not invoice:
        return ok({"message": "Invoice not found"}, 404)
    if method(request, "PATCH"):
        data = body(request)
        updates = {key: data[key] for key in ["customer", "customer_name", "phone", "item", "package_name", "service_type", "amount", "due_at", "status"] if key in data}
        if "amount" in updates:
            updates["amount"] = float(updates["amount"] or 0)
        updates["updated_at"] = iso_now()
        invoices_data[invoice_id] = {**invoice, **updates}
        _save_tenant_extra_dict(tenant_id, "invoices", invoices_data)
        return ok({"success": True, "message": "Invoice saved", "invoice": {"id": invoice_id, **invoice, **updates}})
    return ok({"message": "Method not allowed"}, 405)


def tenant_payments(tenant_id):
    return list_children(f"tenants/{tenant_id}/payments")


def tenant_customers(tenant_id):
    return list_children(f"tenants/{tenant_id}/customers")


def tenant_packages(tenant_id):
    return list_children(f"tenants/{tenant_id}/packages")


def month_key(value):
    dt = parse_date(value)
    return dt.strftime("%b") if dt else ""


def in_range(item_date, start, end):
    if not item_date:
        return False
    if start and item_date < start:
        return False
    if end and item_date > end:
        return False
    return True


def is_current_active_package_customer(customer, now=None, paid_customer_ids=None, paid_usernames=None, paid_phones=None):
    now = now or utcnow()
    paid_customer_ids = {str(value) for value in (paid_customer_ids or set()) if value}
    paid_usernames = {str(value).strip().lower() for value in (paid_usernames or set()) if str(value or "").strip()}
    paid_phones = {str(value).strip() for value in (paid_phones or set()) if str(value or "").strip()}
    if isinstance(customer, Customer):
        customer_id = str(customer.pk)
        status = customer.status
        package = customer.package
        expiry_date = customer.expiry_date
        last_payment_id = customer.last_payment_id
        last_payment_code = customer.last_payment_code
        username = customer.username
        phone = customer.phone
    else:
        customer_id = str((customer or {}).get("id") or "")
        status = (customer or {}).get("status")
        package = (customer or {}).get("package")
        expiry_date = (customer or {}).get("expiry_date")
        last_payment_id = (customer or {}).get("last_payment_id")
        last_payment_code = (customer or {}).get("last_payment_code")
        username = (customer or {}).get("username")
        phone = (customer or {}).get("phone")
    if str(status or "").strip().lower() != "active":
        return False
    if not str(package or "").strip():
        return False
    has_payment = (
        bool(str(last_payment_id or "").strip())
        or bool(str(last_payment_code or "").strip())
        or (customer_id and customer_id in paid_customer_ids)
        or (str(username or "").strip().lower() in paid_usernames)
        or (str(phone or "").strip() in paid_phones)
    )
    if not has_payment:
        return False
    expires_at = parse_date(expiry_date)
    if not expires_at:
        return True
    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
    return expires_at > now


@csrf_exempt
@api_view(["GET"])
@tenant_required
def dashboard_stats(request):
    tenant_id = request.tenant["id"]
    payments_qs = Payment.objects.filter(tenant_id=tenant_id)
    customers_qs = Customer.objects.filter(tenant_id=tenant_id)
    packages_qs = InternetPackage.objects.filter(tenant_id=tenant_id)
    packages_data = [package.as_dict() for package in packages_qs]
    now = utcnow()
    today = now.date()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    def is_daraja_payment(payment):
        method = str(payment.get("payment_method") or payment.get("method") or "").strip().lower()
        provider = str(payment.get("provider") or "").strip().lower()
        return (
            method in {"daraja_paybill", "daraja_buygoods"}
            or bool(payment.get("daraja_receipt_number") or payment.get("mpesa_receipt_number"))
            or bool(payment.get("daraja_checkout_request_id") or payment.get("daraja_merchant_request_id"))
            or (provider == "mpesa" and str(payment.get("collection_account") or "").strip().lower() == "platform_daraja")
        )

    paid_payments = payments_qs.filter(status="success").annotate(
        report_date=Case(
            When(paid_at__isnull=False, paid_at__gt="", then="paid_at"),
            When(initiated_at__isnull=False, initiated_at__gt="", then="initiated_at"),
            default=Value("", output_field=CharField()), output_field=CharField(),
        )
    )
    paid_customer_ids = paid_payments.exclude(customer_id__isnull=True).values("customer_id")
    paid_usernames = paid_payments.exclude(access_username__isnull=True).exclude(access_username="").values("access_username")
    paid_phones = paid_payments.exclude(phone="").values("phone")
    has_successful_payment = (
        Q(last_payment_id__gt="") | Q(last_payment_code__gt="")
        | Q(pk__in=Subquery(paid_customer_ids))
        | Q(username__in=Subquery(paid_usernames)) | Q(phone__in=Subquery(paid_phones))
    )
    current_active_package_customers = customers_qs.filter(status="active").exclude(package="").filter(has_successful_payment).filter(
        Q(expiry_date__isnull=True) | Q(expiry_date="") | Q(expiry_date__gt=now.isoformat())
    )
    revenue_this_month = float(paid_payments.filter(report_date__gte=month_start.isoformat()).aggregate(total=Sum("amount"))["total"] or 0)
    daraja_condition = (
        Q(extra__payment_method__in=["daraja_paybill", "daraja_buygoods"])
        | Q(extra__daraja_receipt_number__gt="") | Q(extra__mpesa_receipt_number__gt="")
        | Q(extra__daraja_checkout_request_id__gt="") | Q(extra__daraja_merchant_request_id__gt="")
        | Q(provider="mpesa", extra__collection_account="platform_daraja")
    )
    revenue_today = float(paid_payments.filter(daraja_condition, report_date__startswith=today.isoformat()).aggregate(total=Sum("amount"))["total"] or 0)
    twelve_month_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=335)).replace(day=1)
    monthly_payment_rows = paid_payments.filter(report_date__gte=twelve_month_start.isoformat()).annotate(month=Substr("report_date", 1, 7)).values("month").annotate(total=Sum("amount"))
    monthly_payment_map = {item["month"]: float(item["total"] or 0) for item in monthly_payment_rows}

    last_12 = []
    for offset in range(11, -1, -1):
        year = now.year
        month = now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        label = datetime(year, month, 1).strftime("%b")
        total = monthly_payment_map.get(f"{year:04d}-{month:02d}", 0)
        last_12.append([label, round(total, 2)])

    days = []
    active_customer_count = current_active_package_customers.count()
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).date()
        label = day.strftime("%a")
        active = active_customer_count
        new = customers_qs.filter(created_at__date=day).count()
        days.append([label, active, new])

    package_counts = {item["package"] or "Unassigned": item["count"] for item in customers_qs.values("package").annotate(count=Count("id"))}
    palette = ["#fa8200", "#2563eb", "#16a34a", "#dc2626", "#9333ea", "#0f766e"]
    package_utilization = [[name, count, palette[index % len(palette)]] for index, (name, count) in enumerate(package_counts.items())]
    package_revenue = {item["package_name"] or "Unassigned": float(item["revenue"] or 0) for item in paid_payments.values("package_name").annotate(revenue=Sum("amount"))}
    # Enrich customer data with RADIUS session data usage when available
    radius_data_usage = {}
    try:
        from billing_api.models import RadiusSession as RadiusSessionModel

        month_ago = now - timedelta(days=30)
        sessions = RadiusSessionModel.objects.filter(
            tenant_id=tenant_id,
            started_at__gte=month_ago,
        ).values("customer__username").annotate(
            total_input=Sum("input_octets"),
            total_output=Sum("output_octets"),
            total_usage=Sum("input_octets") + Sum("output_octets"),
        ).order_by("-total_usage")[:20]
        for s in sessions:
            username = s["customer__username"] or ""
            radius_data_usage[username] = float((s["total_input"] or 0) + (s["total_output"] or 0))
    except Exception:
        pass

    # Compute avg_data_usage per package from RADIUS sessions
    radius_package_usage = defaultdict(float)
    radius_package_count = defaultdict(int)
    try:
        from billing_api.models import RadiusSession as RadiusSessionModel

        month_ago = now - timedelta(days=30)
        pkg_sessions = RadiusSessionModel.objects.filter(
            tenant_id=tenant_id,
            started_at__gte=month_ago,
        ).values("customer__package").annotate(
            total_input=Sum("input_octets"),
            total_output=Sum("output_octets"),
            session_count=Count("id"),
        )
        for s in pkg_sessions:
            pkg_name = s["customer__package"] or "Unassigned"
            total_bytes = float((s["total_input"] or 0) + (s["total_output"] or 0))
            radius_package_usage[pkg_name] += total_bytes
            radius_package_count[pkg_name] += int(s["session_count"] or 0)
    except Exception:
        pass

    package_performance = []
    active_package_counts = {item["package"]: item["count"] for item in current_active_package_customers.values("package").annotate(count=Count("id"))}
    for package in packages_data:
        name = package.get("name")
        active_count = active_package_counts.get(name, 0)
        revenue = package_revenue.get(name, 0)
        # Use real RADIUS data usage if available, fall back to package field
        if name in radius_package_usage and radius_package_count.get(name, 0) > 0:
            avg_bytes = radius_package_usage[name] / radius_package_count[name]
            avg_usage_mb = round(avg_bytes / (1024 * 1024), 2)
        else:
            avg_usage_mb = float(package.get("avg_data_usage") or 0)
        package_performance.append(
            {
                "name": name,
                "price": float(package.get("price") or 0),
                "active_users": active_count,
                "monthly_revenue": round(revenue, 2),
                "avg_data_usage": avg_usage_mb,
                "arpu": round(revenue / active_count, 2) if active_count else 0,
                "sync_status": package.get("ppp_profile_status") or "pending",
            }
        )

    pppoe_customers_count = customers_qs.filter(Q(service_type="pppoe") | Q(service_type="")).count()
    hotspot_customers_count = customers_qs.filter(service_type="hotspot").count()
    active_hotspot_users = current_active_package_customers.filter(
        service_type="hotspot", username__in=list(radius_data_usage)[:20]
    ).values("username", "phone", "extra")
    def snapshot_active_sessions(router_snapshot):
        migration = ((router_snapshot or {}).get("migration_export") or {})
        ppp_rows = migration.get("ppp_active_sessions") or []
        hotspot_rows = migration.get("hotspot_active_sessions") or []

        def numeric_bytes(item):
            total = 0
            for key in ("bytes_in", "bytes_out", "bytes-in", "bytes-out", "input_octets", "output_octets"):
                try:
                    total += int(float((item or {}).get(key) or 0))
                except (TypeError, ValueError):
                    pass
            return total

        items = [
            {
                "username": item.get("name") or item.get("user") or "-",
                "service_type": "pppoe",
                "address": item.get("address") or item.get("caller_id") or "",
                "mac_address": item.get("caller_id") or "",
                "uptime": item.get("uptime") or "",
                "data_used": numeric_bytes(item),
                "server": item.get("service") or "",
            }
            for item in ppp_rows
            if isinstance(item, dict)
        ] + [
            {
                "username": item.get("user") or item.get("name") or item.get("mac_address") or "-",
                "service_type": "hotspot",
                "address": item.get("address") or "",
                "mac_address": item.get("mac_address") or "",
                "uptime": item.get("uptime") or "",
                "data_used": numeric_bytes(item),
                "server": item.get("server") or "",
            }
            for item in hotspot_rows
            if isinstance(item, dict)
        ]
        items = sorted(items, key=lambda item: item["data_used"], reverse=True)
        return {"pppoe": len(ppp_rows), "hotspot": len(hotspot_rows), "total": len(items), "items": items}

    snapshot = request.tenant.get("mikrotik_router_snapshot") or {}
    router_sample_source = "provisioning_snapshot"
    try:
        if has_mikrotik_credentials(request.tenant):
            snapshot = router_interface_status(request.tenant)
            router_sample_source = "routeros_api"
    except Exception as exc:
        logger.warning("Dashboard live MikroTik sample failed tenant=%s error=%s", tenant_id, exc)
    device = snapshot.get("device") or {}
    cpu_load = device.get("cpu_load")
    last_seen = parse_date(request.tenant.get("mikrotik_last_seen_at"))
    agent_online = bool(last_seen and utcnow() - last_seen <= timedelta(minutes=3))
    router_status = "suspended" if request.tenant.get("mikrotik_router_suspended") else "online" if router_sample_source == "routeros_api" or agent_online else "offline"
    total_customer_count = customers_qs.count()
    active_ratio = (active_customer_count / total_customer_count * 100) if total_customer_count else 0
    traffic = snapshot.get("traffic") or {}
    traffic_bps = int(traffic.get("rx_bps") or 0) + int(traffic.get("tx_bps") or 0)
    signal_values = [
        int(item.get("signal_strength"))
        for item in snapshot.get("interfaces", [])
        if str(item.get("signal_strength") or "").lstrip("-").isdigit()
    ]
    if signal_values:
        strongest_signal = max(signal_values)
        internet_strength_percent = max(0, min(100, round((strongest_signal + 90) / 40 * 100)))
        internet_strength_source = "wireless_signal"
    else:
        internet_strength_source = "router_link"
        enabled_interfaces = [
            item for item in snapshot.get("interfaces", [])
            if not item.get("disabled")
        ]
        running_interfaces = [
            item for item in enabled_interfaces
            if item.get("running")
        ]
        internet_strength_percent = round((len(running_interfaces) / len(enabled_interfaces)) * 100) if enabled_interfaces else (100 if router_sample_source == "routeros_api" else 0)
    traffic_percent = round(min((traffic_bps / 1_000_000), 100), 1) if traffic_bps and router_status == "online" else 0
    active_sessions = snapshot.get("active_sessions") if isinstance(snapshot.get("active_sessions"), dict) else snapshot_active_sessions(snapshot)
    active_session_items = active_sessions.get("items") if isinstance(active_sessions, dict) else []
    active_session_usernames = {
        str(item.get("username") or "").strip().lower()
        for item in (active_session_items or [])
        if isinstance(item, dict) and str(item.get("username") or "").strip()
    }
    radius_active_session_count = 0
    radius_active_session_items = []
    try:
        from billing_api.models import RadiusSession as RadiusSessionModel

        radius_active = RadiusSessionModel.objects.filter(tenant_id=tenant_id, stopped_at__isnull=True)
        radius_active_session_count = radius_active.count()
        active_session_usernames.update(
            str(username or "").strip().lower()
            for username in radius_active.values_list("customer__username", flat=True)
            if str(username or "").strip()
        )
        radius_active_session_items = [
            {
                "username": session.customer.username,
                "service_type": session.service_type or session.customer.service_type,
                "address": session.framed_ip or session.nas_ip,
                "mac_address": "",
                "uptime": str(now - session.started_at).split(".", 1)[0] if session.started_at else "",
                "data_used": float((session.input_octets or 0) + (session.output_octets or 0)),
                "server": session.nas_ip,
            }
            for session in radius_active.select_related("customer").order_by("-started_at")[:5]
        ]
    except Exception:
        pass
    router_active_session_count = int((active_sessions or {}).get("total") or len(active_session_items or [])) if isinstance(active_sessions, dict) else 0
    connected_users_count = len(active_session_usernames) or max(router_active_session_count, radius_active_session_count)
    enabled_customers_count = active_customer_count
    top_active_sessions = [
        {
            "username": item.get("username") or "-",
            "service_type": item.get("service_type") or "",
            "address": item.get("address") or "",
            "mac_address": item.get("mac_address") or "",
            "uptime": item.get("uptime") or "",
            "data_used": float(item.get("data_used") or 0),
            "server": item.get("server") or "",
        }
        for item in (active_session_items or [])[:5]
        if isinstance(item, dict)
    ] or radius_active_session_items

    return ok(
        {
            "summary": {
                "revenue_this_month": round(revenue_this_month, 2),
                "revenue_today": round(revenue_today, 2),
                "sms_balance": float(request.tenant.get("sms_balance") or 0),
                "total_customers": total_customer_count,
                "pppoe_customers": pppoe_customers_count,
                "hotspot_customers": hotspot_customers_count,
                "active_customers": enabled_customers_count,
                "enabled_customers": enabled_customers_count,
                "connected_users": connected_users_count,
                "daraja_revenue_today": round(revenue_today, 2),
            },
            "router_health": {
                "status": router_status,
                "board_name": device.get("board_name") or request.tenant.get("mikrotik_detected_board"),
                "cpu_load_percent": cpu_load,
                "internet_strength_percent": internet_strength_percent,
                "internet_strength_source": internet_strength_source,
                "traffic_percent": traffic_percent,
                "network_traffic_bps": traffic_bps if router_status == "online" else 0,
                "network_rx_bps": traffic.get("rx_bps") if router_status == "online" else 0,
                "network_tx_bps": traffic.get("tx_bps") if router_status == "online" else 0,
                "active_sessions": active_sessions,
                "top_active_sessions": top_active_sessions,
                "sample_source": router_sample_source,
                "sampled_at": traffic.get("sampled_at") or iso_now(),
            },
            "payments_chart": last_12,
            "active_users_chart": days,
            "retention_chart": [[item[0], item[1], max(0, item[1] - item[2]), 90] for item in days[-6:]],
            "data_usage_chart": [[item[0], float(index * 8 + item[1])] for index, item in enumerate(days[-8:])],
            "package_utilization": package_utilization,
            "revenue_forecast": last_12[-6:] + [[f"+{i}", round((last_12[-1][1] if last_12 else 0) * (1 + i * 0.05), 2)] for i in range(1, 4)],
            "sms_chart": [[item[0], int(request.tenant.get("sms_sent_today") or 0)] for item in days],
            "most_active_users": sorted(
                [{"username": c["username"] or c["phone"], "phone": c["phone"], "data_used": radius_data_usage.get(c["username"], float((c["extra"] or {}).get("data_used") or (c["extra"] or {}).get("data_usage") or 0))}
                 for c in customers_qs.filter(username__in=list(radius_data_usage)[:20]).values("username", "phone", "extra")],
                key=lambda item: item["data_used"], reverse=True,
            )[:6],
            "top_hotspot_active_users": sorted(
                [{"username": c["username"] or c["phone"], "phone": c["phone"], "data_used": radius_data_usage.get(c["username"], float((c["extra"] or {}).get("data_used") or (c["extra"] or {}).get("data_usage") or 0))}
                 for c in active_hotspot_users],
                key=lambda item: item["data_used"],
                reverse=True,
            )[:5],
            "package_performance": package_performance,
        }
    )


@csrf_exempt
@api_view(["GET"])
@tenant_required
def report_revenue(request):
    start = request.GET.get("from")
    end = request.GET.get("to")
    payments = Payment.objects.filter(tenant_id=request.tenant["id"], status="success")
    payments = payments.annotate(
        report_date=Case(
            When(paid_at__isnull=False, paid_at__gt="", then="paid_at"),
            When(initiated_at__isnull=False, initiated_at__gt="", then="initiated_at"),
            default=Value("", output_field=CharField()), output_field=CharField(),
        )
    )
    if start:
        payments = payments.filter(report_date__gte=start)
    if end:
        payments = payments.filter(report_date__lt=f"{end}T23:59:59.999999Z")
    rows = list(payments.annotate(month=Substr("report_date", 1, 7)).values("month").annotate(revenue=Sum("amount")).order_by("month"))
    results = [{"month": row["month"], "revenue": round(float(row["revenue"] or 0), 2)} for row in rows if row["month"]]
    return ok({"results": results, "total": round(sum(item["revenue"] for item in results), 2)})


@csrf_exempt
@api_view(["GET"])
@tenant_required
def report_customers(request):
    customers = Customer.objects.filter(tenant_id=request.tenant["id"])
    start = parse_date(request.GET.get("from"))
    end = parse_date(request.GET.get("to"))
    scoped = customers
    if start:
        scoped = scoped.filter(created_at__gte=start)
    if end:
        scoped = scoped.filter(created_at__lte=end)
    grouped = scoped.annotate(month=TruncMonth("created_at")).values("month").annotate(new_customers=Count("id")).order_by("month")
    rows = [{"month": item["month"].strftime("%Y-%m"), "new_customers": item["new_customers"]} for item in grouped if item["month"]]
    total = scoped.count()
    expired_qs = customers.exclude(expiry_date__isnull=True).exclude(expiry_date="").filter(expiry_date__lt=iso_now())
    if start:
        expired_qs = expired_qs.filter(created_at__gte=start)
    if end:
        expired_qs = expired_qs.filter(created_at__lte=end)
    return ok({"results": rows, "total_customers": total, "expired_customers": expired_qs.count()})


@csrf_exempt
@api_view(["GET"])
@tenant_required
def report_packages(request):
    tenant_id = request.tenant["id"]
    active_counts = {item["package"]: item["count"] for item in Customer.objects.filter(tenant_id=tenant_id, status="active").values("package").annotate(count=Count("id"))}
    revenues = {item["package_name"]: float(item["revenue"] or 0) for item in Payment.objects.filter(tenant_id=tenant_id, status="success").values("package_name").annotate(revenue=Sum("amount"))}
    rows = [{"package": package.name, "price": float(package.price or 0), "active_customers": active_counts.get(package.name, 0), "revenue": round(revenues.get(package.name, 0), 2)} for package in InternetPackage.objects.filter(tenant_id=tenant_id).only("name", "price")]
    return ok({"results": rows})


@csrf_exempt
@api_view(["GET"])
@tenant_required
def report_expenses(request):
    expenses = request.tenant.get("expenses") or []
    if not isinstance(expenses, list):
        expenses = []
    start = parse_date(request.GET.get("from"))
    end = parse_date(request.GET.get("to"))
    start_date = start.date() if start else None
    end_date = end.date() if end else None
    by_category = defaultdict(float)
    for expense in expenses:
        expense_date = parse_date(
            expense.get("paid_at")
            or expense.get("date")
            or expense.get("created_at")
        )
        current_date = expense_date.date() if expense_date else None
        if start_date and (not current_date or current_date < start_date):
            continue
        if end_date and (not current_date or current_date > end_date):
            continue
        by_category[expense.get("category") or "Other"] += float(expense.get("amount") or 0)
    revenue = 0.0
    for payment in tenant_payments(request.tenant["id"]):
        if payment.get("status") != "success":
            continue
        paid_at = payment_date(payment)
        paid_date = paid_at.date() if paid_at else None
        if start_date and (not paid_date or paid_date < start_date):
            continue
        if end_date and (not paid_date or paid_date > end_date):
            continue
        revenue += float(payment.get("amount") or 0)
    total_expenses = sum(by_category.values())
    return ok({"results": [{"category": key, "amount": round(value, 2)} for key, value in sorted(by_category.items())], "total_expenses": round(total_expenses, 2), "net_revenue": round(revenue - total_expenses, 2)})


def _save_tenant_extra_postgres(tenant_id, key, value):
    tenant_record = Tenant.objects.get(pk=tenant_id)
    tenant_extra = dict(tenant_record.extra or {})
    tenant_extra[key] = value
    tenant_record.extra = tenant_extra
    tenant_record.save(update_fields=["extra", "updated_at"])


@csrf_exempt
@api_view(["POST"])
@tenant_required
def request_payment_change_code(request):
    tenant = request.tenant
    phone = normalize_phone(tenant.get("phone") or tenant.get("support_phone"))
    email = str(tenant.get("email") or tenant.get("support_email") or "").strip()
    if not phone and not email:
        return ok({"message": "Add a tenant phone number or email before changing payment settings."}, 400)

    code = f"{secrets.randbelow(1000000):06d}"
    challenge_id = secrets.token_urlsafe(18)
    expires_at = (timezone.now() + timedelta(minutes=10)).isoformat()
    challenge = {
        "id": challenge_id,
        "code_hash": hash_password(code),
        "expires_at": expires_at,
        "attempts": 0,
        "used": False,
        "created_at": iso_now(),
    }
    _save_tenant_extra_postgres(tenant["id"], "payment_change_challenge", challenge)
    message = f"Your Expressnet payment settings confirmation code is {code}. It expires in 10 minutes. Do not share it."
    channels = []
    if phone:
        whatsapp = send_whatsapp_message(phone, message, tenant)
        if whatsapp.get("sent"):
            channels.append("whatsapp")
        sms = send_sms_message(phone, message, tenant)
        if sms.get("sent"):
            channels.append("sms")
    if email:
        sent = send_system_email("Payment settings confirmation code", message, [email])
        if sent:
            channels.append("email")
    if not channels:
        _save_tenant_extra_postgres(tenant["id"], "payment_change_challenge", {})
        return ok(
            {
                "success": True,
                "password_fallback": True,
                "message": "The confirmation code could not be delivered. Enter your account password to confirm this change.",
            }
        )
    return ok({"success": True, "challenge_id": challenge_id, "expires_in": 600, "channels": sorted(set(channels))})


@csrf_exempt
@api_view(["GET", "PATCH"])
@tenant_required
def settings_business(request):
    tenant_id = request.tenant["id"]
    if method(request, "GET"):
        return ok(tenant_theme_payload(request.tenant))

    data = body(request)
    if "business_name" in data:
        business_name = str(data.get("business_name") or "").strip()
        if not business_name:
            return ok({"message": "Business name cannot be empty"}, 400)
        current_business_name = str(request.tenant.get("business_name") or "").strip()
        if (business_name.lower() != current_business_name.lower() and (
                Tenant.objects.annotate(normalized_business=Lower(Trim("business_name"))).filter(normalized_business=business_name.lower()).exclude(pk=tenant_id).exists()
                or SchemaTenant.objects.annotate(normalized_business=Lower(Trim("business_name"))).filter(normalized_business=business_name.lower()).exclude(pk=tenant_id).exists())):
            return ok({"message": "A business with this name already exists"}, 409)
    allowed = [
        "business_name",
        "owner_name",
        "phone",
        "support_email",
        "theme_color",
        "font",
        "dark_mode",
        "theme_mode",
        "business_number",
        "payout_phone",
        "bank_code",
        "bank_name",
        "bank_daraja_shortcode",
        "daraja_settlement_till_number",
        "settlement_destination_type",
        "bank_account_number",
        "payment_methods",
        "payment_provider",
        "daraja_consumer_key",
        "daraja_consumer_secret",
        "daraja_shortcode",
        "daraja_passkey",
        "daraja_till_number",
        "daraja_shortcode_type",
        "daraja_environment",
        "payment_customer_email",
    ]
    updates = {}
    if "business_name" in data:
        updates["business_name"] = str(data["business_name"]).strip()
    requested_payment_fields = PAYMENT_SETTING_FIELDS.intersection(data)
    changed_payment_fields = {
        field for field in requested_payment_fields
        if data.get(field) != request.tenant.get(field)
    }
    if changed_payment_fields:
        challenge = request.tenant.get("payment_change_challenge") or {}
        challenge_id = str(data.get("payment_change_id") or "").strip()
        challenge_code = str(data.get("payment_change_code") or "").strip()
        current_password = str(data.get("current_password") or "")
        expires_at = parse_datetime(str(challenge.get("expires_at") or ""))
        password_confirmed = bool(current_password and check_password(current_password, request.tenant.get("password")))
        challenge_confirmed = bool(
            challenge_id
            and challenge_id == challenge.get("id")
            and not challenge.get("used")
            and expires_at
            and expires_at > timezone.now()
            and int(challenge.get("attempts") or 0) < 5
            and check_password(challenge_code, challenge.get("code_hash"))
        )
        if not challenge_confirmed and not password_confirmed:
            attempts = int(challenge.get("attempts") or 0) + 1 if challenge else 0
            if challenge:
                challenge["attempts"] = attempts
                _save_tenant_extra_postgres(tenant_id, "payment_change_challenge", challenge)
            return ok({"message": "A valid confirmation code or account password is required to change payment settings."}, 403)
        if challenge_confirmed:
            challenge["used"] = True
            challenge["used_at"] = iso_now()
            _save_tenant_extra_postgres(tenant_id, "payment_change_challenge", challenge)
    for field in allowed:
        if field in data:
            if field == "dark_mode":
                updates[field] = bool(data[field])
            elif field == "payment_methods":
                requested = data[field] if isinstance(data[field], list) else [data[field]]
                normalized_methods = []
                for item in requested:
                    value = str(item).strip().lower()
                    if value in {"paybill", "mpesa_paybill"}:
                        value = "daraja_paybill"
                    elif value in {"buygoods", "buy_goods", "mpesa_buygoods"}:
                        value = "daraja_buygoods"
                    if value in {"daraja_paybill", "daraja_buygoods", "till", "bank", "phone"}:
                        normalized_methods.append(value)
                updates[field] = normalized_methods or ["daraja_paybill"]
            elif field == "payment_provider":
                updates[field] = "mpesa"
            elif field == "daraja_shortcode_type":
                value = str(data[field] or "").strip()
                updates[field] = value if value in {"CustomerPayBillOnline", "CustomerBuyGoodsOnline"} else "CustomerPayBillOnline"
            elif field == "daraja_environment":
                value = str(data[field] or "production").strip().lower()
                updates[field] = "sandbox" if value == "sandbox" else "production"
            elif field == "bank_daraja_shortcode":
                updates[field] = "".join(ch for ch in str(data[field] or "") if ch.isdigit())
            elif field == "bank_code":
                updates[field] = str(data[field] or "").strip()
                updates["bank_daraja_shortcode"] = updates[field]
            elif field == "daraja_settlement_till_number":
                updates[field] = "".join(ch for ch in str(data[field] or "") if ch.isdigit())
            elif field == "settlement_destination_type":
                destination_type = str(data[field] or "").strip().lower()
                updates[field] = destination_type if destination_type in {"bank", "till", "phone"} else "bank"
            elif field in {"daraja_consumer_key", "daraja_consumer_secret", "daraja_passkey"}:
                # Blank values preserve the server-side credential. Secrets are
                # never sent back to the browser after they have been saved.
                if str(data[field] or "").strip():
                    updates[field] = str(data[field])
            else:
                updates[field] = str(data[field]).strip()
    if updates.get("theme_mode") not in {None, "light", "dark", "system"}:
        updates["theme_mode"] = "dark"
    if "theme_mode" in updates:
        updates["dark_mode"] = updates["theme_mode"] == "dark"
    if "theme_color" in updates and not updates["theme_color"].startswith("#"):
        updates["theme_color"] = f"#{updates['theme_color']}"
    updates["business_settings_updated_at"] = iso_now()

    merged = {**request.tenant, **updates}
    updates["payment_provider"] = "mpesa"
    updates["settlement_status"] = daraja_b2b_settlement_status(merged)

    merged = {**request.tenant, **updates}

    tenant_record = Tenant.objects.get(pk=tenant_id)
    tenant_record.apply_data(updates)
    try:
        tenant_record.save()
    except IntegrityError:
        return ok({"message": "A business with this name already exists"}, 409)
    return ok({"success": True, "message": "Business settings saved", "config": tenant_theme_payload({**merged, **updates})})


@csrf_exempt
@api_view(["GET"])
@tenant_required
def payment_banks(request):
    # Daraja B2B uses bank M-Pesa Paybill shortcodes, not Paystack bank codes.
    return ok({"results": [
        {"code": "522522", "name": "KCB Bank", "daraja_shortcode": "522522"},
        {"code": "247247", "name": "Equity Bank", "daraja_shortcode": "247247"},
        {"code": "400200", "name": "Co-operative Bank", "daraja_shortcode": "400200"},
        {"code": "880100", "name": "NCBA Bank", "daraja_shortcode": "880100"},
        {"code": "303030", "name": "Absa Bank Kenya", "daraja_shortcode": "303030"},
        {"code": "329329", "name": "Standard Chartered Bank", "daraja_shortcode": "329329"},
        {"code": "600100", "name": "Stanbic Bank Kenya", "daraja_shortcode": "600100"},
        {"code": "222111", "name": "Family Bank", "daraja_shortcode": "222111"},
        {"code": "542542", "name": "I&M Bank", "daraja_shortcode": "542542"},
        {"code": "516600", "name": "Diamond Trust Bank", "daraja_shortcode": "516600"},
        {"code": "700201", "name": "Ecobank Kenya", "daraja_shortcode": "700201"},
        {"code": "985050", "name": "Gulf African Bank", "daraja_shortcode": "985050"},
        {"code": "", "name": "Other bank (enter its Paybill)", "daraja_shortcode": ""},
    ]})


@csrf_exempt
@api_view(["GET", "PATCH"])
@tenant_required
def profile(request):
    if method(request, "GET"):
        return ok({"owner_name": request.tenant.get("owner_name") or "", "email": request.tenant.get("email") or "", "phone": request.tenant.get("phone") or "", "business_name": request.tenant.get("business_name") or ""})
    data = body(request)
    updates = {}
    if "owner_name" in data:
        updates["owner_name"] = str(data.get("owner_name") or "").strip()
    if "phone" in data:
        updates["phone"] = str(data.get("phone") or "").strip()
    if "email" in data and str(data.get("email") or "").strip().lower() != request.tenant.get("email"):
        if not check_password(data.get("current_password", ""), request.tenant.get("password")):
            return ok({"message": "Current password is required to change email"}, 400)
        updates["email"] = str(data["email"]).strip().lower()
    if data.get("new_password"):
        if not check_password(data.get("current_password", ""), request.tenant.get("password")):
            return ok({"message": "Current password is incorrect"}, 400)
        if data.get("new_password") != data.get("confirm_password"):
            return ok({"message": "New password and confirmation do not match"}, 400)
        updates["password"] = hash_password(data["new_password"])
    if not updates:
        return ok({"message": "No profile fields provided"}, 400)
    ref(f"tenants/{request.tenant['id']}").update({**updates, "profile_updated_at": iso_now()})
    return ok({"success": True, "message": "Profile updated"})


@csrf_exempt
@api_view(["POST"])
@tenant_required
def settings_logo(request):
    upload = request.FILES.get("logo")
    if not upload:
        return ok({"message": "Logo file is required"}, 400)
    if upload.size > 2 * 1024 * 1024:
        return ok({"message": "Logo must be smaller than 2MB"}, 400)
    ext = Path(upload.name).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return ok({"message": "Logo must be PNG, JPG, WEBP, or SVG"}, 400)
    storage = FileSystemStorage(location=Path(settings.MEDIA_ROOT) / "tenant-logos", base_url=f"{settings.MEDIA_URL}tenant-logos/")
    filename = storage.save(f"tenant-{request.tenant['id']}{ext}", upload)
    logo_url = storage.url(filename)
    ref(f"tenants/{request.tenant['id']}").update({"logo_url": logo_url, "logo_updated_at": iso_now()})
    return ok({"success": True, "message": "Logo uploaded", "logo_url": logo_url})


@csrf_exempt
@api_view(["POST"])
@tenant_required
def settings_test_sms(request):
    data = body(request)
    phone = normalize_phone(data.get("phone") or request.tenant.get("phone"))
    if not phone:
        return ok({"message": "Phone number is required"}, 400)
    channel = str(data.get("channel") or "whatsapp").strip().lower()
    test_message = str(data.get("message") or "This is a test message from Expressnet.").strip()
    if channel == "sms":
        result = send_sms_message(phone, test_message, request.tenant)
    else:
        result = send_whatsapp_message(phone, test_message, request.tenant)
    if result.get("sent"):
        return ok({"success": True, "message": f"Test {channel} sent", "phone": phone, "result": result})
    return ok({"success": False, "message": result.get("skipped") or result.get("error") or f"Failed to send test {channel}", "phone": phone, "result": result}, 400)


@csrf_exempt
@api_view(["POST"])
@tenant_required
def settings_test_whatsapp(request):
    data = body(request)
    phone = normalize_phone(data.get("phone") or request.tenant.get("phone"))
    if not phone:
        return ok({"message": "Phone number is required to test WhatsApp notifications"}, 400)
    test_message = str(data.get("message") or "This is a test WhatsApp notification from Expressnet.").strip()
    tenant = {
        **request.tenant,
        "notification_provider": str(data.get("provider") or request.tenant.get("notification_provider") or "slek").strip(),
        "whatsapp_enabled": data.get("whatsapp_enabled") is not False,
    }
    apiwap_api_key = str(data.get("apiwap_api_key") or "").strip()
    if apiwap_api_key and apiwap_api_key not in {MASKED, "********", "••••••••"}:
        tenant["apiwap_api_key"] = apiwap_api_key
    if data.get("apiwap_base_url"):
        tenant["apiwap_base_url"] = str(data.get("apiwap_base_url")).strip()
    result = send_whatsapp_message(phone, test_message, tenant)
    if result.get("sent"):
        return ok({"success": True, "message": "Test WhatsApp notification sent", "phone": phone, "result": result})
    reason = result.get("skipped") or result.get("error") or "Failed to send test WhatsApp notification"
    return ok({"success": False, "message": reason, "phone": phone, "result": result}, 400)


@csrf_exempt
@api_view(["GET", "POST", "PATCH", "DELETE"])
@tenant_required
def tickets(request, ticket_id=None):
    tenant_id = request.tenant["id"]
    if method(request, "GET") and not ticket_id:
        items = list_children(f"tenants/{tenant_id}/tickets")
        status_filter = request.GET.get("status")
        if status_filter and status_filter != "all":
            items = [item for item in items if item.get("status") == status_filter]
        return as_collection_response(request, items)
    if method(request, "POST") and not ticket_id:
        data = body(request)
        if not data.get("title"):
            return ok({"message": "Ticket title is required"}, 400)
        ticket_ref = ref(f"tenants/{tenant_id}/tickets").push(
            {
                "title": str(data.get("title") or "").strip(),
                "description": str(data.get("description") or "").strip(),
                "customer_id": str(data.get("customer_id") or "").strip(),
                "assigned_to": str(data.get("assigned_to") or "").strip(),
                "assigned_to_name": str(data.get("assigned_to_name") or "").strip(),
                "assigned_to_role": str(data.get("assigned_to_role") or "").strip(),
                "mikrotik_id": str(data.get("mikrotik_id") or "").strip(),
                "mikrotik_name": str(data.get("mikrotik_name") or "").strip(),
                "status": data.get("status") or "open",
                "priority": data.get("priority") or "medium",
                "created_at": iso_now(),
                "updated_at": iso_now(),
            }
        )
        return ok({"success": True, "message": "Ticket created", "ticketId": ticket_ref.key}, 201)
    if not ticket_id:
        return ok({"message": "Ticket id is required"}, 400)
    ticket = ref(f"tenants/{tenant_id}/tickets/{ticket_id}").get()
    if not ticket:
        return ok({"message": "Ticket not found"}, 404)
    if method(request, "PATCH"):
        data = body(request)
        allowed = ["title", "description", "customer_id", "assigned_to", "assigned_to_name", "assigned_to_role", "mikrotik_id", "mikrotik_name", "status", "priority"]
        updates = {field: data[field] for field in allowed if field in data}
        if updates.get("status") in {"resolved", "closed"} and not ticket.get("resolved_at"):
            updates["resolved_at"] = iso_now()
        updates["updated_at"] = iso_now()
        ref(f"tenants/{tenant_id}/tickets/{ticket_id}").update(updates)
        return ok({"success": True, "message": "Ticket updated", "ticket": {"id": ticket_id, **ticket, **updates}})
    if method(request, "DELETE"):
        ref(f"tenants/{tenant_id}/tickets/{ticket_id}").delete()
        return ok({"success": True, "message": "Ticket deleted"})
    return ok({"message": "Method not allowed"}, 405)


@csrf_exempt
@api_view(["POST"])
@tenant_required
def settings_delete_customers(request):
    data = body(request)
    if str(data.get("confirm") or "").strip() != str(request.tenant.get("business_name") or "").strip():
        return ok({"message": "Type your business name exactly to confirm"}, 400)
    customers_data = list_children(f"tenants/{request.tenant['id']}/customers")
    for customer in customers_data:
        try:
            delete_router_customer(request.tenant, customer.get("username"), customer.get("service_type") or "pppoe")
        except Exception:
            pass
        ref(f"tenants/{request.tenant['id']}/customers/{customer['id']}").delete()
    return ok({"success": True, "message": f"Deleted {len(customers_data)} customers"})


@csrf_exempt
@api_view(["GET", "PATCH"])
@tenant_required
def settings_mikrotik(request):
    if method(request, "GET"):
        linked_routers = request.tenant.get("linked_routers") or {}
        if _router_is_agent_linked(request.tenant) and not linked_routers:
            linked_routers = {"primary": _linked_router_from_tenant(request.tenant)}
        return ok({
            "mikrotik_host": request.tenant.get("mikrotik_host", ""),
            "mikrotik_user": request.tenant.get("mikrotik_user", ""),
            "mikrotik_port": int(request.tenant.get("mikrotik_port") or 8728),
            "has_mikrotik_password": bool(request.tenant.get("mikrotik_pass")),
            "mikrotik_provisioning_status": request.tenant.get("mikrotik_provisioning_status", ""),
            "mikrotik_provisioned_at": request.tenant.get("mikrotik_provisioned_at", ""),
            "mikrotik_last_seen_at": request.tenant.get("mikrotik_last_seen_at", ""),
            "mikrotik_last_seen_ip": request.tenant.get("mikrotik_last_seen_ip", ""),
            "mikrotik_detected_identity": request.tenant.get("mikrotik_detected_identity", ""),
            "mikrotik_detected_version": request.tenant.get("mikrotik_detected_version", ""),
            "mikrotik_detected_board": request.tenant.get("mikrotik_detected_board", ""),
            "linked_routers": linked_routers,
            "router_port_assignments": request.tenant.get("router_port_assignments") or {},
        })
    data = body(request)
    updates = {}
    for field in ["mikrotik_host", "mikrotik_user", "mikrotik_pass"]:
        if field in data and (field != "mikrotik_pass" or str(data[field]).strip()):
            updates[field] = str(data[field]).strip() if field != "mikrotik_pass" else str(data[field])
    if "mikrotik_port" in data:
        updates["mikrotik_port"] = int(data.get("mikrotik_port") or 8728)
    if "mikrotik_port" in updates and not 1 <= updates["mikrotik_port"] <= 65535:
        return ok({"message": "MikroTik port must be between 1 and 65535"}, 400)
    updates["mikrotik_updated_at"] = iso_now()
    ref(f"tenants/{request.tenant['id']}").update(updates)
    merged = {**request.tenant, **updates}
    return ok({"success": True, "message": "MikroTik configuration saved", "config": {"mikrotik_host": merged.get("mikrotik_host", ""), "mikrotik_user": merged.get("mikrotik_user", ""), "mikrotik_port": int(merged.get("mikrotik_port") or 8728), "has_mikrotik_password": bool(merged.get("mikrotik_pass"))}})


@csrf_exempt
@api_view(["POST"])
@tenant_required
def settings_mikrotik_test(request):
    candidate = {**request.tenant, **body(request)}
    if not candidate.get("mikrotik_pass"):
        return ok({"message": "MikroTik password is required to test the connection"}, 400)
    try:
        profiles = router_items(candidate, "ppp", "profile")
        return ok({"success": True, "mode": "routeros_api", "message": "MikroTik live API connection successful.", "profile_count": len(profiles)})
    except (TimeoutError, OSError) as exc:
        live_error = str(exc)
    except Exception as exc:
        live_error = str(exc)

    snapshot = request.tenant.get("mikrotik_router_snapshot") or {}
    status = request.tenant.get("mikrotik_provisioning_status")
    if status in {"script_downloaded", "completed"} or snapshot:
        return ok({
            "success": True,
            "mode": "provisioning_callback",
            "message": "Router provisioning is connected. The router successfully reached this app.",
            "profile_count": len((snapshot.get("profiles") or {}).get("pppoe") or []),
            "warning": f"Using provisioning snapshot/agent mode. Live RouterOS API is not reachable from the server yet: {live_error}",
        })
    return ok({"message": f"Unable to reach MikroTik live API. Confirm public host/port forwarding to {candidate.get('mikrotik_port') or 8728}: {live_error}"}, 400)


@csrf_exempt
@api_view(["GET", "PATCH"])
@tenant_required
def settings_notifications(request):
    if method(request, "GET"):
        return ok(
            {
                "provider": request.tenant.get("notification_provider") or "slek",
                "sms_enabled": request.tenant.get("sms_enabled") is not False,
                "sms_on_maintenance": request.tenant.get("sms_on_maintenance") is not False,
                "sms_on_promotions": request.tenant.get("sms_on_promotions") is not False,
                "sms_on_payment": request.tenant.get("sms_on_payment") is not False,
                "whatsapp_on_customer_created": request.tenant.get("whatsapp_on_customer_created") is not False,
                "whatsapp_on_expiry": request.tenant.get("whatsapp_on_expiry") is not False,
                "sms_template_maintenance": request.tenant.get("sms_template_maintenance") or "We will be performing scheduled maintenance. Thank you for your patience.",
                "sms_template_promotion": request.tenant.get("sms_template_promotion") or "Special offer from {{business}}: {{message}}",
                "sms_template_hotspot": strip_customer_template_tokens(request.tenant.get("sms_template_hotspot") or "Your hotspot package is active."),
                "sms_template_pppoe": strip_customer_template_tokens(request.tenant.get("sms_template_pppoe") or "Your PPPoE package is active."),
                "sms_balance": int(request.tenant.get("sms_balance") or 0),
                "sms_sent_count": int(request.tenant.get("sms_sent_count") or 0),
                "whatsapp_enabled": request.tenant.get("whatsapp_enabled") is not False,
                "roamtech_sender_id": request.tenant.get("roamtech_sender_id") or "",
                "apiwap_base_url": request.tenant.get("apiwap_base_url") or "https://api.apiwap.com/api/v1",
                "has_apiwap_api_key": bool(request.tenant.get("apiwap_api_key")),
            }
        )
    data = body(request)
    updates = {
        "notification_provider": str(data.get("provider") or "slek").strip(),
        "sms_enabled": data.get("sms_enabled") is not False,
        "sms_on_maintenance": data.get("sms_on_maintenance") is not False,
        "sms_on_promotions": data.get("sms_on_promotions") is not False,
        "sms_on_payment": data.get("sms_on_payment") is not False,
        "whatsapp_on_customer_created": data.get("whatsapp_on_customer_created") is not False,
        "whatsapp_on_expiry": data.get("whatsapp_on_expiry") is not False,
        "sms_template_maintenance": str(data.get("sms_template_maintenance") or "").strip(),
        "sms_template_promotion": str(data.get("sms_template_promotion") or "").strip(),
        "sms_template_hotspot": strip_customer_template_tokens(data.get("sms_template_hotspot") or ""),
        "sms_template_pppoe": strip_customer_template_tokens(data.get("sms_template_pppoe") or ""),
        "whatsapp_enabled": data.get("whatsapp_enabled") is not False,
        "roamtech_sender_id": str(data.get("roamtech_sender_id") or "").strip(),
        "apiwap_base_url": str(data.get("apiwap_base_url") or "https://api.apiwap.com/api/v1").strip(),
        "notifications_updated_at": iso_now(),
    }
    apiwap_api_key = str(data.get("apiwap_api_key") or "").strip()
    if apiwap_api_key and apiwap_api_key not in {MASKED, "********", "••••••••"}:
        updates["apiwap_api_key"] = apiwap_api_key
    ref(f"tenants/{request.tenant['id']}").update(updates)
    try:
        tenant_obj = Tenant.objects.get(pk=request.tenant["id"])
        tenant_obj.apply_data(updates)
        tenant_obj.save()
    except Tenant.DoesNotExist:
        logger.warning("Notification settings could not be matched to a tenant model tenant=%s", request.tenant["id"])
    saved = {**request.tenant, **updates}
    return ok({
        "success": True,
        "message": "Notification settings saved",
        "config": {key: value for key, value in updates.items() if key != "apiwap_api_key"},
        "provider": saved.get("notification_provider") or "slek",
        "whatsapp_enabled": saved.get("whatsapp_enabled") is not False,
        "has_apiwap_api_key": bool(saved.get("apiwap_api_key")),
        "apiwap_base_url": saved.get("apiwap_base_url") or "https://api.apiwap.com/api/v1",
    })


def to_access_username(phone):
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def _payment_customer_name(payment, phone, username):
    return str(phone or username or "Customer").strip()


def _upsert_sql_customer(tenant_id, data):
    try:
        tenant_obj = Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        logger.warning("Paid access SQL customer sync skipped; tenant model not found tenant=%s", tenant_id)
        return None

    username = str(data.get("username") or "").strip()
    phone = str(data.get("phone") or "").strip()
    customer = None
    if username:
        customer = Customer.objects.filter(tenant=tenant_obj, username=username).first()
    if not customer and phone:
        customer = Customer.objects.filter(tenant=tenant_obj, phone=phone).first()
    if not customer:
        customer = Customer(tenant=tenant_obj)

    customer.apply_data(data)
    if not customer.radius_secret:
        customer.radius_secret = customer.password or ""
    customer.save()
    return customer


def _upsert_sql_paystack_payment(tenant_id, payment_id, payment_data):
    """Store customer portal Paystack payment details in the tenant SQL ledger."""
    if not payment_data:
        return None
    reference = str(payment_data.get("paystack_reference") or "").strip()
    try:
        tenant_obj = Tenant.objects.filter(pk=tenant_id).first()
        if not tenant_obj:
            logger.warning("Paystack SQL payment sync skipped; tenant model not found tenant=%s payment=%s", tenant_id, payment_id)
            return None
        sql_payment = Payment.objects.filter(tenant=tenant_obj, paystack_reference=reference).first() if reference else None
        if not sql_payment:
            sql_payment = Payment(tenant=tenant_obj)
        fields = {
            "customer_name": payment_data.get("customer_name"),
            "package_id": str(payment_data.get("package_id") or "") or None,
            "package_name": payment_data.get("package_name"),
            "service_type": payment_data.get("service_type") or "hotspot",
            "amount": payment_data.get("amount") or payment_data.get("amount_payable") or 0,
            "payment_code": payment_data.get("payment_code"),
            "provider": "paystack",
            "currency": payment_data.get("currency") or "KES",
            "phone": payment_data.get("phone") or "",
            "status": payment_data.get("status") or "pending",
            "paid_at": payment_data.get("paid_at"),
            "initiated_at": payment_data.get("initiated_at") or iso_now(),
            "paystack_reference": reference or None,
            "paystack_access_code": payment_data.get("paystack_access_code"),
            "paystack_authorization_url": payment_data.get("paystack_authorization_url"),
            "paystack_transaction_id": payment_data.get("paystack_transaction_id"),
            "paystack_channel": payment_data.get("paystack_channel"),
            "paystack_paid_at": payment_data.get("paystack_paid_at"),
            "source": payment_data.get("source") or "customer_portal",
            "access_username": payment_data.get("access_username"),
            "access_password": payment_data.get("access_password"),
            "access_expires_at": payment_data.get("access_expires_at"),
            "access_status": payment_data.get("access_status"),
            "customer_id": payment_data.get("customer_id"),
        }
        for field, value in fields.items():
            setattr(sql_payment, field, value)
        extra = dict(sql_payment.extra or {})
        extra.update({
            "tenant_settlement_status": payment_data.get("tenant_settlement_status"),
            "collection_account": payment_data.get("collection_account"),
            "tenant_paystack_subaccount_code": payment_data.get("tenant_paystack_subaccount_code"),
            "payout_model": payment_data.get("payout_model"),
            "platform_fee_percent": payment_data.get("platform_fee_percent"),
            "paystack_processing_fee": payment_data.get("paystack_processing_fee"),
            "platform_fee_amount": payment_data.get("platform_fee_amount"),
            "tenant_payout_amount": payment_data.get("tenant_payout_amount"),
            "access_error": payment_data.get("access_error"),
            "last_synced_at": iso_now(),
        })
        sql_payment.extra = extra
        sql_payment.save()
        return sql_payment
    except Exception:
        logger.exception("Paystack SQL payment sync failed tenant=%s payment=%s reference=%s", tenant_id, payment_id, reference)
        return None


def _find_paystack_payment(reference):
    """Resolve a Paystack reference directly against the tenant SQL ledger."""
    payment = Payment.objects.filter(paystack_reference=reference).first()
    if payment:
        return str(payment.tenant_id), str(payment.pk)
    return None


def _numeric_pk(value):
    text = str(value or "").strip()
    return text if text.isdigit() else None


def render_notification_template(template, context):
    rendered = str(template or "")
    for key, value in context.items():
        rendered = rendered.replace("{{" + key + "}}", str(value if value is not None else ""))
    return rendered


def strip_customer_template_tokens(template):
    rendered = str(template or "")
    for token in ["name", "username", "package", "amount_payable", "password", "amount", "expires_at"]:
        rendered = rendered.replace("{{" + token + "}}", "")
    return " ".join(rendered.split()).strip()


def append_payment_access_details(message, context):
    base = str(message or "").strip() or "Your internet package is active."
    details = (
        f"Name: {context.get('name') or 'customer'}. "
        f"Package: {context.get('package') or ''}. "
        f"Amount: Ksh {context.get('amount_payable') or context.get('amount') or ''}. "
        f"Username: {context.get('username') or ''}. "
        f"Password: {context.get('password') or ''}."
    )
    return f"{base} {details}"


def append_expiry_details(message, context):
    base = str(message or "").strip() or "Your internet package is about to expire."
    details = (
        f"Name: {context.get('name') or 'customer'}. "
        f"Package: {context.get('package') or ''}. "
        f"Username: {context.get('username') or ''}. "
        f"Expires: {context.get('expires_at') or ''}."
    )
    return f"{base} {details}"


def append_customer_created_details(message, context):
    service_label = str(context.get("service_type") or "internet").upper()
    base = str(message or "").strip() or f"Your {service_label} account has been created."
    details = (
        f"Name: {context.get('name') or 'customer'}. "
        f"Package: {context.get('package') or ''}. "
        f"Amount payable: Ksh {context.get('amount_payable') or ''}. "
        "Your technician will assist with setup."
    )
    return f"{base} {details}"


def notification_brand(tenant):
    return (tenant or {}).get("business_name") or (tenant or {}).get("name") or "Expressnet"


def support_contact(tenant):
    return (tenant or {}).get("phone") or (tenant or {}).get("support_phone") or (tenant or {}).get("support_email") or ""


def system_customer_created_message(tenant, context):
    brand = notification_brand(tenant)
    package_name = context.get("package") or ""
    amount = context.get("amount_payable") or ""
    return (
        f"Welcome to {brand}! Your internet account has been successfully created.\n\n"
        f"Package: {package_name}\n"
        f"Amount Payable: KSh {amount}\n\n"
        "Please make payment to activate your internet service.\n\n"
        f"Thank you for choosing {brand}."
    )


def system_payment_message(tenant, context):
    brand = notification_brand(tenant)
    amount = context.get("amount_payable") or context.get("amount") or ""
    package_name = context.get("package") or ""
    message = f"Payment received! We have successfully received your payment of KSh {amount} for the {package_name} package.\n\n"
    if context.get("payment_code"):
        message += f"M-Pesa receipt: {context['payment_code']}\n\n"
    return message + "Your payment has been confirmed and your internet service is being activated.\n\n" + f"Thank you for choosing {brand}."


def system_expiry_message(tenant, context):
    brand = notification_brand(tenant)
    return (
        f"{brand} Reminder: Your {context.get('package') or ''} package will expire on {context.get('expires_at') or ''}.\n\n"
        "Please renew your package before the expiry date to avoid interruption of your internet service.\n\n"
        f"Thank you for choosing {brand}."
    )


def append_technician_credentials_details(message, context):
    service_label = str(context.get("service_type") or "internet").upper()
    base = str(message or "").strip() or f"A {service_label} customer account has been created."
    network_details = ""
    if context.get("ip_address"):
        network_details = (
            f" IP address: {context.get('ip_address') or ''}. "
            f"Subnet mask: {context.get('subnet_mask') or ''}. "
            f"Gateway: {context.get('gateway') or ''}. "
            f"Preferred DNS: {context.get('preferred_dns') or ''}."
        )
    details = (
        f"Customer: {context.get('name') or 'customer'}. "
        f"Phone: {context.get('phone') or ''}. "
        f"Package: {context.get('package') or ''}. "
        f"Amount payable: Ksh {context.get('amount_payable') or ''}. "
        f"Username: {context.get('username') or ''}. "
        f"Password: {context.get('password') or ''}."
        f"{network_details}"
    )
    return f"{base} {details}"


def notify_customer_created(tenant, customer):
    service_type = str((customer or {}).get("service_type") or "").strip().lower()
    if service_type not in {"pppoe", "static"}:
        return {"whatsapp": {"sent": False, "skipped": "unsupported_service_type"}}
    if (tenant or {}).get("whatsapp_enabled") is False or (tenant or {}).get("whatsapp_on_customer_created") is False:
        return {"whatsapp": {"sent": False, "skipped": "disabled"}}
    technician = _find_team_member_by_label(tenant, customer.get("technician"))
    context = {
        "name": customer.get("name") or customer.get("phone") or "customer",
        "phone": customer.get("phone") or "",
        "package": customer.get("package") or customer.get("package_name") or "",
        "service_type": service_type,
        "amount_payable": customer.get("amount_payable") or "",
        "username": customer.get("username") or "",
        "password": customer.get("password") or "",
        "ip_address": customer.get("ip_address") or "",
        "subnet_mask": customer.get("subnet_mask") or "",
        "gateway": customer.get("gateway") or "",
        "preferred_dns": customer.get("preferred_dns") or "",
    }
    technician_template = (tenant or {}).get("technician_customer_credentials_template") or f"A {service_type.upper()} customer account has been created."
    results = {
        "customer_whatsapp": send_whatsapp_message(
            customer.get("phone"),
            system_customer_created_message(tenant, context),
            tenant,
            recipient_name=context["name"],
        )
    }
    if technician and technician.get("phone"):
        results["technician_whatsapp"] = send_whatsapp_message(
            technician.get("phone"),
            append_technician_credentials_details(strip_customer_template_tokens(technician_template), context),
            tenant,
            recipient_name=technician.get("name") or "Technician",
        )
    else:
        results["technician_whatsapp"] = {"sent": False, "skipped": "missing_technician_phone"}
    results["whatsapp"] = results["customer_whatsapp"]
    return results


def _invoice_id():
    return f"INV-{timezone.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"


def create_customer_invoice(tenant, customer, amount, reason="subscription_due", due_at=None):
    tenant_id = tenant.get("id")
    if not tenant_id:
        return None
    invoice_id = secrets.token_hex(8)
    invoice = {
        "invoice_number": _invoice_id(),
        "customer_id": customer.get("id"),
        "customer": customer.get("name") or customer.get("phone") or "Customer",
        "customer_name": customer.get("name") or customer.get("phone") or "Customer",
        "phone": customer.get("phone") or "",
        "item": f"{customer.get('package') or 'Internet'} subscription",
        "package_name": customer.get("package") or "",
        "service_type": customer.get("service_type") or "",
        "amount": float(amount or 0),
        "due_at": due_at or iso_now(),
        "status": "sent",
        "reason": reason,
        "created_at": iso_now(),
        "updated_at": iso_now(),
    }
    invoices_data = _tenant_extra_dict(tenant_id, "invoices")
    invoices_data[invoice_id] = invoice
    _save_tenant_extra_dict(tenant_id, "invoices", invoices_data)
    return {"id": invoice_id, **invoice}


def mark_customer_invoice_paid(tenant_id, customer_id, payment):
    if not customer_id:
        return None
    invoices = [{"id": invoice_id, **invoice} for invoice_id, invoice in _tenant_extra_dict(tenant_id, "invoices").items()]
    open_invoice = next(
        (
            invoice for invoice in sorted(invoices, key=lambda item: item.get("created_at") or "", reverse=True)
            if str(invoice.get("customer_id") or "") == str(customer_id) and invoice.get("status") != "paid"
        ),
        None,
    )
    if not open_invoice:
        return None
    updates = {
        "status": "paid",
        "paid_at": payment.get("paid_at") or iso_now(),
        "payment_id": payment.get("id"),
        "payment_code": payment.get("payment_code"),
        "updated_at": iso_now(),
    }
    invoices_data = _tenant_extra_dict(tenant_id, "invoices")
    invoices_data[open_invoice["id"]] = {**invoices_data.get(open_invoice["id"], {}), **updates}
    _save_tenant_extra_dict(tenant_id, "invoices", invoices_data)
    return {"id": open_invoice["id"], **open_invoice, **updates}


def notify_payment_access(tenant, payment, access):
    amount_payable = payment.get("amount_payable") or payment.get("amount") or ""
    notification_context = {
        "name": payment.get("customer_name") or payment.get("phone") or "customer",
        "package": payment.get("package_name") or "",
        "amount": payment.get("amount") or "",
        "amount_payable": amount_payable,
        "username": access.get("username") or access.get("mac_address") or "",
        "password": access.get("password") or "",
        "expires_at": access.get("expiry_date") or "",
        "payment_code": payment.get("payment_code") or payment.get("daraja_receipt_number") or "",
    }
    message = system_payment_message(tenant, notification_context)
    results = {}
    if (tenant or {}).get("sms_on_payment") is not False:
        balance = int((tenant or {}).get("sms_balance") or 0)
        if balance <= 0:
            results["sms"] = {"sent": False, "skipped": "sms_balance_empty"}
        else:
            results["sms"] = send_sms_message(payment.get("phone"), message, tenant)
            if results["sms"].get("sent"):
                tenant_id = tenant.get("id")
                if tenant_id:
                    ref(f"tenants/{tenant_id}").update({"sms_balance": balance - 1, "sms_sent_count": int((tenant or {}).get("sms_sent_count") or 0) + 1})
    if (tenant or {}).get("whatsapp_enabled") is not False:
        customer_name = notification_context["name"]
        results["whatsapp"] = send_whatsapp_message(
            payment.get("phone"),
            message,
            tenant,
            recipient_name=customer_name,
        )
    return results


def notify_package_expiry(tenant, customer):
    if (tenant or {}).get("whatsapp_enabled") is False or (tenant or {}).get("whatsapp_on_expiry") is False:
        return {"whatsapp": {"sent": False, "skipped": "disabled"}}
    context = {
        "name": customer.get("name") or customer.get("phone") or "customer",
        "package": customer.get("package") or "",
        "username": customer.get("username") or "",
        "expires_at": customer.get("expiry_date") or customer.get("expires_at") or "",
    }
    message = system_expiry_message(tenant, context)
    return {
        "whatsapp": send_whatsapp_message(
            customer.get("phone"),
            message,
            tenant,
            recipient_name=context["name"],
        )
    }


@csrf_exempt
@api_view(["POST"])
@tenant_required
def send_expiry_notifications(request):
    data = body(request)
    hours = int(data.get("hours") or 24)
    now = timezone.now()
    due_at = now + timedelta(hours=hours)
    sent = []
    skipped = []
    invoices_created = []
    for customer in list_children(f"tenants/{request.tenant['id']}/customers"):
        expiry_raw = customer.get("expiry_date") or customer.get("expires_at")
        if not expiry_raw:
            continue
        expiry = parse_datetime(str(expiry_raw))
        if not expiry:
            continue
        if expiry.tzinfo is None:
            expiry = timezone.make_aware(expiry, timezone.get_current_timezone())
        if expiry > due_at:
            continue
        invoice_marker = f"expiry_invoice_{expiry.date().isoformat()}"
        if expiry <= now and not customer.get(invoice_marker):
            amount_due = customer.get("amount_payable")
            if amount_due in {None, ""}:
                pkg = find_child_by_field(f"tenants/{request.tenant['id']}/packages", "name", customer.get("package"))
                amount_due = (pkg or {}).get("amount_payable") or (pkg or {}).get("price") or 0
            invoice = create_customer_invoice(request.tenant, customer, amount_due, reason="subscription_expired", due_at=expiry.isoformat())
            if invoice:
                ref(f"tenants/{request.tenant['id']}/customers/{customer['id']}").update({invoice_marker: invoice["id"], "last_expiry_invoice_at": iso_now()})
                invoices_created.append(invoice)
        marker = f"expiry_whatsapp_notice_{expiry.date().isoformat()}"
        if customer.get(marker):
            skipped.append({"customer_id": customer.get("id"), "reason": "already_notified"})
            continue
        result = notify_package_expiry(request.tenant, customer)
        if result.get("whatsapp", {}).get("sent"):
            ref(f"tenants/{request.tenant['id']}/customers/{customer['id']}").update({marker: iso_now(), "last_expiry_notification_at": iso_now()})
            sent.append({"customer_id": customer.get("id"), "phone": customer.get("phone")})
        else:
            skipped.append({"customer_id": customer.get("id"), "phone": customer.get("phone"), "result": result})
    return ok({"success": True, "message": f"Sent {len(sent)} expiry WhatsApp notifications", "sent": sent, "skipped": skipped, "invoices_created": invoices_created})


def activate_paid_access(tenant, payment_id, payment, phone, payment_code, notify=True):
    tenant_id = tenant["id"]
    package_name = payment.get("package_name")
    tenant_obj = Tenant.objects.filter(pk=tenant_id).first()
    pg_payment_id = _numeric_pk(payment_id)
    pg_customer_id = _numeric_pk(payment.get("customer_id"))
    pg_payment = Payment.objects.filter(tenant_id=tenant_id, pk=pg_payment_id).first() if pg_payment_id else None
    if not pg_payment and payment.get("paystack_reference"):
        pg_payment = Payment.objects.filter(tenant_id=tenant_id, paystack_reference=payment.get("paystack_reference")).first()
    pg_customer = None
    if pg_payment and pg_payment.customer_id:
        pg_customer = pg_payment.customer
    if not pg_customer and pg_customer_id:
        pg_customer = Customer.objects.filter(tenant_id=tenant_id, pk=pg_customer_id).first()
    if not pg_customer and payment.get("username"):
        pg_customer = Customer.objects.filter(tenant_id=tenant_id, username__iexact=payment.get("username")).first()
    if not pg_customer and phone:
        pg_customer = Customer.objects.filter(tenant_id=tenant_id, phone=str(phone)).first()
    customers_data = list_children(f"tenants/{tenant_id}/customers")
    customer = None
    if payment.get("customer_id"):
        customer = next((c for c in customers_data if str(c.get("id")) == str(payment.get("customer_id"))), None)
    if not customer and payment.get("username"):
        customer = next((c for c in customers_data if str(c.get("username") or "").lower() == str(payment.get("username") or "").lower()), None)
    if not customer and phone:
        customer = next((c for c in customers_data if str(c.get("phone")) == str(phone)), None)
    if not customer and pg_customer:
        customer = pg_customer.as_dict()
    service_type = payment.get("service_type") or (customer or {}).get("service_type") or "hotspot"
    package_for_access = package_name or (customer or {}).get("package")
    pg_package = InternetPackage.objects.filter(tenant_id=tenant_id, name=package_for_access).first() if package_for_access else None
    pkg = pg_package.as_dict() if pg_package else find_child_by_field(f"tenants/{tenant_id}/packages", "name", package_for_access)
    duration = package_duration_delta(pkg)
    is_bundle = package_is_bundle(pkg)
    duration_seconds = None if is_bundle else int(duration.total_seconds())
    expiry = utcnow() + timedelta(days=3650) if is_bundle else package_expiry_date(utcnow(), pkg)
    if payment.get("status") == "success":
        existing_expiry = payment.get("access_expires_at") or (customer or {}).get("expiry_date")
        parsed_expiry = parse_datetime(str(existing_expiry or ""))
        if parsed_expiry:
            if timezone.is_naive(parsed_expiry):
                parsed_expiry = timezone.make_aware(parsed_expiry, timezone.get_current_timezone())
            if parsed_expiry > utcnow():
                expiry = parsed_expiry
    limit_bytes_total = package_data_limit_bytes(pkg)
    router_client_mac = normalize_mac(payment.get("router_client_mac") or payment.get("router_mac"))
    router_client_ip = str(payment.get("router_client_ip") or payment.get("ip") or "").strip()
    mac_address = normalize_mac(payment.get("mac_address") or (router_client_mac if service_type == "hotspot" else "") or (customer or {}).get("mac_address"))
    static_ip_address = str(payment.get("ip_address") or (customer or {}).get("ip_address") or "").strip()
    username = mac_address if service_type == "tv" else (payment.get("access_username") or payment.get("username") or (customer or {}).get("username") or to_access_username(phone))
    password = str(payment.get("pending_access_password") or payment.get("access_password") or (customer or {}).get("password") or payment_code)
    customer_name = _payment_customer_name({**(customer or {}), **payment}, phone, username)
    auto_authorize_mac = service_type == "hotspot" and bool(router_client_mac)
    if customer:
        updates = {"name": customer_name, "phone": phone, "username": username, "password": password, "package": package_for_access, "service_type": service_type, "status": "active", "expiry_date": expiry.isoformat(), "last_payment_id": payment_id, "last_payment_code": payment_code, "auto_reconnect": True, "router_client_mac": router_client_mac, "router_client_ip": router_client_ip, "auto_authorize_mac": auto_authorize_mac, "updated_at": iso_now()}
        if mac_address:
            updates["mac_address"] = mac_address
        ref(f"tenants/{tenant_id}/customers/{customer['id']}").update(updates)
        customer_id = customer["id"]
    else:
        new_ref = ref(f"tenants/{tenant_id}/customers").push({"name": customer_name, "phone": phone, "username": username, "password": password, "package": package_for_access, "service_type": service_type, "status": "active", "expiry_date": expiry.isoformat(), "last_payment_id": payment_id, "last_payment_code": payment_code, "auto_reconnect": True, "mac_address": mac_address, "router_client_mac": router_client_mac, "router_client_ip": router_client_ip, "auto_authorize_mac": auto_authorize_mac, "created_at": iso_now()})
        customer_id = new_ref.key
    if service_type == "tv" and not mac_address:
        raise ValueError("TV MAC address is required for activation")
    sql_customer = None
    try:
        sql_customer = _upsert_sql_customer(
            tenant_id,
            {
                "name": customer_name,
                "phone": phone,
                "username": username,
                "password": password,
                "radius_secret": password,
                "package": package_for_access,
                "service_type": service_type,
                "status": "active",
                "expiry_date": expiry.isoformat(),
                "auto_reconnect": True,
                "last_payment_id": payment_id,
                "last_payment_code": payment_code,
                "mac_address": mac_address,
                "router_client_mac": router_client_mac,
                "router_client_ip": router_client_ip,
                "auto_authorize_mac": auto_authorize_mac,
            },
        )
    except Exception as exc:
        logger.warning("Paid access SQL customer sync failed tenant=%s payment=%s username=%s error=%s", tenant_id, payment_id, username, exc, exc_info=True)
    radius_access_ready = False
    if tenant.get("radius_enabled") and service_type in {"hotspot", "pppoe"}:
        try:
            from billing_api.radius_provisioning import sync_radius_customer, upsert_pg_customer

            tenant_obj = tenant_obj or Tenant.objects.get(pk=tenant_id)
            pg_customer = sql_customer or upsert_pg_customer(tenant_obj, {"name": customer_name, "phone": phone, "username": username, "password": password, "package": package_for_access, "service_type": service_type, "status": "active", "expiry_date": expiry.isoformat(), "last_payment_id": payment_id, "last_payment_code": payment_code})
            sync_radius_customer(tenant_obj, pg_customer or {"username": username, "password": password})
            radius_access_ready = True
            logger.info(
                "Paid access prepared for RADIUS tenant=%s payment=%s username=%s service=%s package=%s expires_at=%s",
                tenant_id,
                payment_id,
                username,
                service_type,
                package_for_access,
                expiry.isoformat(),
            )
        except Exception as exc:
            logger.warning("Paid access RADIUS sync failed tenant=%s payment=%s username=%s error=%s", tenant_id, payment_id, username, exc, exc_info=True)
            ref(f"tenants/{tenant_id}/payments/{payment_id}").update({"radius_status": "failed", "radius_error": str(exc)})
    router_access_status = "active"
    router_access_error = None
    access_payload = {
        "username": username,
        "password": password,
        "package_name": package_for_access,
        "package": package_for_access,
        "service_type": service_type,
        "mac_address": mac_address,
        "router_client_mac": router_client_mac,
        "router_client_ip": router_client_ip,
        # Captive clients have already supplied this MAC in the router's
        # redirect.  Authorize it locally as soon as M-Pesa confirms payment;
        # this removes dependence on a captive-browser auto-submit retry.
        "auto_authorize_mac": auto_authorize_mac,
        "ip_address": static_ip_address,
        "subnet_mask": ((customer or {}).get("subnet_mask") or "255.255.0.0") if service_type == "static" else (customer or {}).get("subnet_mask"),
        "gateway": ((customer or {}).get("gateway") or "172.30.0.1") if service_type == "static" else (customer or {}).get("gateway"),
        "preferred_dns": ((customer or {}).get("preferred_dns") or "172.30.0.1") if service_type == "static" else (customer or {}).get("preferred_dns"),
        "duration_seconds": duration_seconds,
        "limit_bytes_total": limit_bytes_total,
        "expires_at": expiry.isoformat(),
        "status": "active",
        "speed": (pkg or {}).get("speed"),
    }
    if has_mikrotik_credentials(tenant):
        try:
            if service_type == "hotspot" and pkg:
                create_hotspot_profile(tenant, pkg["name"], pkg.get("speed"), duration_seconds)
            if service_type == "pppoe" and pkg:
                create_ppp_profile(tenant, pkg["name"], pkg.get("speed"), duration_seconds)
            upsert_customer_access(tenant, access_payload)
            # ``upsert_customer_access`` creates the RouterOS user enabled,
            # refreshes the active Hotspot MAC binding, and applies the speed
            # queue in the same pooled binary-API session.  A second enable
            # call only added network round trips and could interrupt the
            # just-authorized client.
            router_access_status = "active"
        except Exception as exc:
            if _router_is_agent_linked(tenant):
                _queue_router_command_for_tenant(tenant_id, {
                    "type": "sync_secrets",
                    "script": _customer_secret_script(access_payload),
                    "customer_ids": [customer_id],
                    "payment_ids": [payment_id],
                })
                router_access_status = "queued"
                router_access_error = str(exc)
            else:
                raise
    elif _router_is_agent_linked(tenant):
        _queue_router_command_for_tenant(tenant_id, {
            "type": "sync_secrets",
            "script": _customer_secret_script(access_payload),
            "customer_ids": [customer_id],
            "payment_ids": [payment_id],
        })
        router_access_status = "queued"
    elif tenant.get("radius_enabled") and radius_access_ready and service_type in {"hotspot", "pppoe"}:
        router_access_status = "radius_ready"
        router_access_error = None
        logger.info(
            "Paid access activation prepared for RADIUS tenant=%s payment=%s username=%s; no direct router channel is available for local user sync",
            tenant_id,
            payment_id,
            username,
        )
    else:
        router_access_status = "pending"
        router_access_error = "Customer access could not be synchronized to the router or RADIUS service"
    payment_access_updates = {
        "customer_id": customer_id,
        "access_username": username,
        "access_password": password,
        "access_mac_address": mac_address,
        "access_expires_at": expiry.isoformat(),
        "access_status": router_access_status,
        "access_error": router_access_error,
        "auto_reconnect": True,
    }
    ref(f"tenants/{tenant_id}/payments/{payment_id}").update(payment_access_updates)
    try:
        pg_payment = pg_payment or (Payment.objects.filter(tenant_id=tenant_id, pk=pg_payment_id).first() if pg_payment_id else None)
        if pg_payment:
            pg_payment.status = "success"
            pg_payment.payment_code = payment_code or pg_payment.payment_code
            pg_payment.phone = phone or pg_payment.phone
            pg_payment.package_name = package_for_access or pg_payment.package_name
            pg_payment.service_type = service_type or pg_payment.service_type
            pg_payment.access_username = username
            pg_payment.access_password = password
            pg_payment.access_expires_at = expiry.isoformat()
            pg_payment.access_status = router_access_status
            if sql_customer:
                pg_payment.customer = sql_customer
            extra = dict(pg_payment.extra or {})
            extra.update(
                {
                    "access_mac_address": mac_address,
                    "access_error": router_access_error,
                    "auto_reconnect": True,
                    "last_activation_at": iso_now(),
                }
            )
            pg_payment.extra = extra
            pg_payment.save()
    except Exception as exc:
        logger.warning("Paid access SQL payment sync failed tenant=%s payment=%s username=%s error=%s", tenant_id, payment_id, username, exc, exc_info=True)
    access = {"username": username, "password": password, "mac_address": mac_address, "expiry_date": expiry.isoformat()}
    if notify:
        try:
            notify_result = notify_payment_access(tenant, {**payment, "phone": phone, "package_name": package_for_access}, access)
            if notify_result:
                sent_channels = [name for name, result in notify_result.items() if result.get("sent")]
                skipped = "; ".join(f"{name}: {result.get('skipped')}" for name, result in notify_result.items() if result.get("skipped"))
                ref(f"tenants/{tenant_id}/payments/{payment_id}").update({"notification_status": "sent" if sent_channels else "skipped", "notification_channels": sent_channels, "notification_detail": skipped})
        except Exception as exc:
            ref(f"tenants/{tenant_id}/payments/{payment_id}").update({"whatsapp_status": "failed", "whatsapp_detail": str(exc)})
    publish_realtime_event(
        tenant_id,
        "payment.updated",
        {
            "payment_id": str(payment_id),
            "status": "success",
            "access_status": router_access_status,
            "access_error": router_access_error or "",
        },
        payment_id=payment_id,
    )
    return access


def _queue_paid_access_activation(tenant_id, payment_id, reason="payment confirmation"):
    """Queue the slow router/RADIUS work without delaying a payment callback."""
    from billing_api.tasks import activate_paid_payment

    now = iso_now()
    ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
        "access_status": "activation_pending",
        "access_error": "",
        "activation_queued_at": now,
        "activation_queue_reason": reason,
    })
    publish_realtime_event(
        tenant_id,
        "payment.updated",
        {
            "payment_id": str(payment_id),
            "status": "success",
            "access_status": "activation_pending",
        },
        payment_id=payment_id,
    )
    try:
        activate_paid_payment.delay(str(tenant_id), str(payment_id))
        return True
    except Exception:
        # Keep the durable pending state.  A later verification request or the
        # reconciliation task can enqueue it once the broker is available.
        logger.exception("Could not enqueue paid access activation tenant=%s payment=%s", tenant_id, payment_id)
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
            "access_error": "Activation is queued and will retry when the worker is available.",
            "activation_enqueue_failed_at": now,
        })
        return False


def _activate_paid_access_immediately(tenant_id, payment_id, reason="payment confirmation"):
    """Activate paid local Hotspot access without relying on Celery/RADIUS.

    The STK callback marks a payment successful only after Safaricom confirms
    it.  At that point the customer path must create and enable the RouterOS
    user immediately.  Celery is retained solely as recovery for a temporary
    router failure; it is not allowed to gate internet access.
    """
    payment_path = f"tenants/{tenant_id}/payments/{payment_id}"
    payment = ref(payment_path).get() or {}
    if payment.get("status") != "success":
        return False
    if str(payment.get("access_status") or "").lower() == "active":
        return True

    tenant = {"id": str(tenant_id), **(ref(f"tenants/{tenant_id}").get() or {})}
    # Explicitly bypass any stale tenant flag from an old RADIUS deployment.
    tenant["radius_enabled"] = False
    try:
        activate_paid_access(
            tenant,
            str(payment_id),
            payment,
            payment.get("phone"),
            payment.get("payment_code") or payment.get("daraja_receipt_number") or str(payment_id),
            notify=False,
        )
        current = ref(payment_path).get() or {}
        if str(current.get("access_status") or "").lower() == "active":
            logger.info("Paid access activated directly tenant=%s payment=%s reason=%s", tenant_id, payment_id, reason)
            return True
        logger.warning("Direct paid access did not reach active state tenant=%s payment=%s status=%s", tenant_id, payment_id, current.get("access_status"))
    except Exception:
        logger.exception("Direct paid access activation failed tenant=%s payment=%s", tenant_id, payment_id)
    return False


def _dispatch_tenant_settlement(tenant_id, payment_id):
    """Start B2C/B2B settlement without placing it on the customer path.

    Celery remains the durable dispatcher.  Railway's Beat-only deployment
    can publish jobs without running a worker, so a daemon fallback executes
    the same idempotent task in the web process.  The task row lock ensures
    only one of the worker or fallback can submit a settlement.
    """
    from billing_api.tasks import request_tenant_settlement

    try:
        request_tenant_settlement.delay(str(tenant_id), str(payment_id))
    except Exception:
        logger.exception("Could not enqueue tenant settlement tenant=%s payment=%s", tenant_id, payment_id)

    def run_settlement():
        close_old_connections()
        try:
            request_tenant_settlement.run(str(tenant_id), str(payment_id))
        except Exception:
            logger.exception("Web fallback settlement failed tenant=%s payment=%s", tenant_id, payment_id)
        finally:
            close_old_connections()

    threading.Thread(
        target=run_settlement,
        name=f"expressnet-settlement-{tenant_id}-{payment_id}",
        daemon=True,
    ).start()


def complete_daraja_payment(tenant_id, payment_id, callback_metadata, amount, receipt, paid_at, phone):
    payment = ref(f"tenants/{tenant_id}/payments/{payment_id}").get()
    if not payment:
        logger.warning("Daraja callback payment not found tenant=%s payment=%s receipt=%s", tenant_id, payment_id, receipt)
        return False
    if payment.get("status") == "success":
        access_status = str(payment.get("access_status") or "").lower()
        if access_status != "activation_processing" and (not payment.get("access_username") or access_status in {"", "pending", "activation_pending", "activation_failed"}):
            if not _activate_paid_access_immediately(tenant_id, payment_id, "duplicate Daraja callback"):
                _queue_paid_access_activation(tenant_id, payment_id, "duplicate Daraja callback recovery")
        return True

    expected_amount = round(float(payment.get("amount") or 0), 2)
    paid_amount = round(float(amount or 0), 2)
    if expected_amount and paid_amount != expected_amount:
        logger.warning(
            "Daraja callback amount mismatch tenant=%s payment=%s expected=%s paid=%s receipt=%s",
            tenant_id,
            payment_id,
            expected_amount,
            paid_amount,
            receipt,
        )
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
            "status": "failed",
            "failed_at": iso_now(),
            "callback_result_desc": "Paid amount does not match the package amount",
        })
        return False

    update = {
        "provider": "mpesa",
        "amount": paid_amount,
        "payment_code": receipt,
        "daraja_receipt_number": receipt,
        "daraja_paid_at": paid_at,
        "phone": phone or payment.get("phone"),
        "status": "success",
        "paid_at": iso_now(),
        "callback_result_code": "success",
        "callback_result_desc": "M-Pesa payment successful",
        "collection_account": payment.get("collection_account") or "platform_daraja",
        "tenant_settlement_status": payment.get("tenant_settlement_status") or "queued",
    }
    tenant_data = ref(f"tenants/{tenant_id}").get() or {}
    # Persist payment success before any optional invoice, settlement or
    # notification work.  A failure in one of those integrations must never
    # leave a customer who has paid stuck in the portal's "waiting for
    # confirmation" state.
    ref(f"tenants/{tenant_id}/payments/{payment_id}").update(update)
    try:
        mark_customer_invoice_paid(tenant_id, payment.get("customer_id"), {"id": payment_id, **payment, **update})
    except Exception:
        logger.exception(
            "Could not mark customer invoice paid after confirmed Daraja payment tenant=%s payment=%s",
            tenant_id,
            payment_id,
        )
    collection_account = str(update.get("collection_account") or "").strip().lower()
    platform_collected = collection_account != "tenant_daraja"
    payout = tenant_payout_details(tenant_data)
    settlement_amount = paid_amount
    try:
        platform_fee_percent = float(os.getenv("PLATFORM_FEE_PERCENTAGE", "0") or 0)
    except ValueError:
        platform_fee_percent = 0
    try:
        platform_fee_fixed = float(os.getenv("PLATFORM_FEE_FIXED", "0") or 0)
    except ValueError:
        platform_fee_fixed = 0
    platform_fee = round((settlement_amount * platform_fee_percent / 100) + platform_fee_fixed, 2) if platform_collected else 0
    tenant_net_amount = max(0, round(settlement_amount - platform_fee, 2)) if platform_collected else 0
    settlement_status = daraja_b2b_settlement_status(tenant_data)
    destination_type = payout.get("settlement_destination_type")
    if destination_type == "bank" and not payout.get("bank_daraja_shortcode"):
        tenant_settlement_status = "missing_b2b_destination"
    else:
        tenant_settlement_status = settlement_status
    settlement_provider = "daraja_b2c" if destination_type == "phone" else "daraja_b2b"
    settlement_recipient = (
        payout.get("payout_phone") if destination_type == "phone"
        else payout.get("daraja_settlement_till_number") if destination_type == "till"
        else payout.get("bank_daraja_shortcode")
    )
    update.update({
        "settlement_gross_amount": settlement_amount,
        "settlement_fee_amount": platform_fee,
        "tenant_net_amount": tenant_net_amount,
        "tenant_payout": payout,
        "tenant_settlement_status": ("queued" if tenant_settlement_status == "withdrawal_ready" else tenant_settlement_status) if platform_collected else "not_required",
        "tenant_settlement_queued_at": iso_now() if platform_collected else "",
    })
    ref(f"tenants/{tenant_id}/payments/{payment_id}").update(update)
    # The customer must be online as soon as the STK callback confirms
    # payment.  Use the local RouterOS binary API now; settlement remains a
    # separate background concern.  If the router is briefly unavailable, the
    # durable queue below is recovery only, never the normal access path.
    if not _activate_paid_access_immediately(tenant_id, payment_id, "Daraja callback"):
        _queue_paid_access_activation(tenant_id, payment_id, "Daraja callback router recovery")
    current_balance = float(tenant_data.get("settlement_pending_amount") or 0)
    tenant_balance_update = {
        "settlement_pending_amount": round(current_balance + tenant_net_amount, 2) if platform_collected else current_balance,
        "settlement_status": update["tenant_settlement_status"],
        "settlement_updated_at": iso_now(),
    }
    if platform_collected and tenant_settlement_status == "withdrawal_ready" and tenant_net_amount > 0:
        # Settlement may take tens of seconds.  Persist a durable job first
        # and let a worker submit it, rather than holding the STK callback
        # open long enough for Safaricom to retry it.
        update.update({
            "tenant_settlement_status": "queued",
            "tenant_settlement_provider": settlement_provider,
            "tenant_settlement_recipient": settlement_recipient,
            "tenant_settlement_destination_type": destination_type,
        })
        tenant_balance_update["settlement_status"] = "queued"
    ref(f"tenants/{tenant_id}/payments/{payment_id}").update(update)
    ref(f"tenants/{tenant_id}").update(tenant_balance_update)
    if update.get("tenant_settlement_status") == "queued":
        _dispatch_tenant_settlement(tenant_id, payment_id)
    logger.info("Daraja payment completed tenant=%s payment=%s receipt=%s phone=%s amount=%s", tenant_id, payment_id, receipt, phone or payment.get("phone"), paid_amount)
    return True


@csrf_exempt
@api_view(["POST"])
def local_daraja_test_callback(request, event_type):
    """Accept an ngrok callback from the isolated local Daraja test tool.

    This route is deliberately disabled outside Django DEBUG mode and never
    touches payment, customer, or settlement records.  Production payments
    continue to use their signed per-payment callback route below.
    """
    local_test_callbacks_enabled = str(os.getenv("LOCAL_DARAJA_TEST_CALLBACKS") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not settings.DEBUG and not local_test_callbacks_enabled:
        raise Http404
    if event_type not in {"stk-result", "b2b-result", "b2b-timeout"}:
        raise Http404
    event = body(request)
    root = (event or {}).get("Body") if isinstance((event or {}).get("Body"), dict) else (event or {})
    result = root.get("stkCallback") or root.get("Result") or root
    result = result if isinstance(result, dict) else {}
    logger.info(
        "Local Daraja test callback received type=%s result_code=%s checkout=%s conversation=%s detail=%s",
        event_type,
        result.get("ResultCode"),
        result.get("CheckoutRequestID"),
        result.get("ConversationID"),
        str(result.get("ResultDesc") or "")[:250],
    )
    return ok({"success": True, "test_callback": event_type})


@csrf_exempt
@api_view(["POST"])
def daraja_callback(request, tenant_id, payment_id, token):
    # Daraja has no request-signing mechanism — the per-payment token
    # embedded in the callback URL at STK push time is what stops this
    # endpoint from being used to spoof completion of an arbitrary payment.
    if not verify_daraja_callback_token(tenant_id, payment_id, token):
        logger.warning("Daraja callback rejected invalid token tenant=%s payment=%s", tenant_id, payment_id)
        return ok({"success": False, "message": "Invalid callback token"}, 401)

    event = body(request)
    stk_callback = (((event or {}).get("Body") or {}).get("stkCallback")) or {}
    result_code = stk_callback.get("ResultCode")
    result_desc = stk_callback.get("ResultDesc") or ""
    if str(payment_id).startswith("system-subscription-"):
        items = ((stk_callback.get("CallbackMetadata") or {}).get("Item")) or []
        values = {item.get("Name"): item.get("Value") for item in items if isinstance(item, dict)}
        amount = values.get("Amount")
        receipt = values.get("MpesaReceiptNumber") or ""
        phone = values.get("PhoneNumber") or ""
        subscription = TenantSubscription.objects.select_related("tenant").filter(tenant_id=tenant_id).first()
        if str(result_code) != "0":
            logger.warning(
                "Daraja system subscription callback failed tenant=%s payment=%s result_code=%s result_desc=%s",
                tenant_id,
                payment_id,
                result_code,
                result_desc,
            )
            return ok({"success": True})
        if not subscription:
            logger.warning("Daraja system subscription callback missing subscription tenant=%s payment=%s", tenant_id, payment_id)
            return ok({"success": True})
        now = timezone.now()
        current_expiry = subscription.expires_at if subscription.expires_at and subscription.expires_at > now else now
        period_end = current_expiry + timedelta(days=subscription.billing_cycle_days)
        payment = SubscriptionPayment.objects.create(
            subscription=subscription,
            amount=Decimal(str(amount or subscription.amount or 0)),
            currency=subscription.currency,
            method="mpesa_stk",
            reference=receipt,
            notes=f"System subscription STK payment. Phone: {phone}. Callback: {payment_id}",
            period_start=current_expiry,
            period_end=period_end,
            recorded_by="daraja_callback",
        )
        subscription.last_paid_at = payment.paid_at
        subscription.expires_at = period_end
        subscription.save(update_fields=["last_paid_at", "expires_at", "updated_at"])
        if subscription.tenant.status == "suspended":
            subscription.tenant.status = "active"
            subscription.tenant.save(update_fields=["status", "updated_at"])
            ref(f"tenants/{tenant_id}").update(
                {
                    "status": "active",
                    "subscription_restored_at": iso_now(),
                    "suspended_reason": "",
                    "updated_at": iso_now(),
                }
            )
        logger.info("Daraja system subscription completed tenant=%s payment=%s receipt=%s amount=%s", tenant_id, payment_id, receipt, amount)
        return ok({"success": True})
    ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
        "daraja_callback_received_at": iso_now(),
        "daraja_callback_result_code": result_code,
        "daraja_callback_result_desc": result_desc,
        "daraja_callback_payload": event,
    })

    if str(result_code) != "0":
        logger.warning(
            "Daraja callback failed tenant=%s payment=%s result_code=%s result_desc=%s",
            tenant_id,
            payment_id,
            result_code,
            result_desc,
        )
        ref(f"tenants/{tenant_id}/payments/{payment_id}").update({
            "status": "failed",
            "failed_at": iso_now(),
            "callback_result_code": result_code,
            "callback_result_desc": result_desc or "M-Pesa payment was cancelled or failed",
        })
        # Always 200 back to Safaricom — they retry on non-2xx, we don't
        # want retries for a customer-cancelled payment.
        return ok({"success": True})

    items = ((stk_callback.get("CallbackMetadata") or {}).get("Item")) or []
    values = {item.get("Name"): item.get("Value") for item in items if isinstance(item, dict)}
    amount = values.get("Amount")
    receipt = values.get("MpesaReceiptNumber")
    paid_at = values.get("TransactionDate")
    phone = values.get("PhoneNumber")

    try:
        complete_daraja_payment(tenant_id, payment_id, {}, amount, receipt, paid_at, phone)
    except Exception:
        logger.exception("Daraja callback activation failed tenant=%s payment=%s receipt=%s", tenant_id, payment_id, receipt)
        raise
    return ok({"success": True})


def _find_settlement_payment(provider, occasion="", originator_id="", conversation_id=""):
    """Find one settlement from callback identifiers without scanning ledgers."""
    base = Payment.objects.filter(tenant_settlement_provider=provider)
    if occasion and str(occasion).isdigit():
        payment = base.filter(pk=str(occasion)).first()
        if payment:
            return payment
    callback_ids = Q()
    if originator_id:
        callback_ids |= Q(tenant_settlement_originator_conversation_id=str(originator_id))
    if conversation_id:
        callback_ids |= Q(tenant_settlement_conversation_id=str(conversation_id))
    if callback_ids:
        payment = base.filter(callback_ids).first()
        if payment:
            return payment
        # Temporary compatibility for settlement requests created before the
        # indexed fields were introduced.  New requests never take this path.
        legacy_ids = Q()
        if originator_id:
            legacy_ids |= Q(extra__tenant_settlement_originator_conversation_id=str(originator_id))
        if conversation_id:
            legacy_ids |= Q(extra__tenant_settlement_conversation_id=str(conversation_id))
        return Payment.objects.filter(extra__tenant_settlement_provider=provider).filter(legacy_ids).first()
    return None


def _apply_settlement_result(payment_record, result, callback_status):
    # Provider callbacks can be duplicated or arrive concurrently. Lock both
    # records so a successful payout is subtracted from the pending balance
    # exactly once.
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_record.pk)
        payment_data = payment.as_dict()
        if payment_data.get("tenant_settlement_result_at"):
            return True
        result_code = result.get("ResultCode")
        result_desc = result.get("ResultDesc") or ""
        settlement_status = "timeout" if callback_status == "timeout" else "paid" if str(result_code) == "0" else "failed"
        now = iso_now()
        update = {
            "tenant_settlement_status": settlement_status,
            "tenant_settlement_result_code": result_code,
            "tenant_settlement_result_desc": result_desc,
            "tenant_settlement_result": result,
        }
        receipt = result.get("TransactionID")
        if receipt:
            update["tenant_settlement_receipt"] = receipt
        if callback_status == "timeout":
            update["tenant_settlement_timeout_at"] = now
        else:
            update["tenant_settlement_result_at"] = now
        payment.apply_data(update)
        payment.save()

        tenant = Tenant.objects.select_for_update().get(pk=payment.tenant_id)
        tenant_data = tenant.as_dict()
        pending_balance = float(tenant_data.get("settlement_pending_amount") or 0)
        amount = float(payment_data.get("tenant_net_amount") or 0)
        tenant_update = {
            "settlement_status": settlement_status,
            "settlement_last_result_at": now,
            "settlement_last_result_desc": result_desc or (
                "Settlement timed out; reconcile before retrying." if callback_status == "timeout" else ""
            ),
        }
        # The pending balance is increased when the customer payment succeeds.
        # Only a confirmed settlement removes it.  Previous code added the
        # amount again on a failure, making failed payouts appear twice.
        if settlement_status == "paid":
            tenant_update["settlement_pending_amount"] = max(0, round(pending_balance - amount, 2))
        tenant.apply_data(tenant_update)
        tenant.save()
    return True


def update_b2c_settlement(event, status):
    event = event if isinstance(event, dict) else {}
    body_data = event.get("Body") if isinstance(event.get("Body"), dict) else {}
    result = event.get("Result") or body_data.get("Result") or event
    result = result if isinstance(result, dict) else {}
    originator_id = result.get("OriginatorConversationID") or event.get("OriginatorConversationID") or ""
    conversation_id = result.get("ConversationID") or event.get("ConversationID") or ""
    occasion = result.get("Occasion") or event.get("Occasion") or ""
    payment = _find_settlement_payment("daraja_b2c", occasion, originator_id, conversation_id)
    return _apply_settlement_result(payment, result, status) if payment else False


@csrf_exempt
@api_view(["POST"])
def daraja_b2c_result(request):
    matched = update_b2c_settlement(body(request), "result")
    if not matched:
        logger.warning("Daraja B2C result did not match a payment")
    return ok({"success": True})


@csrf_exempt
@api_view(["POST"])
def daraja_b2c_timeout(request):
    matched = update_b2c_settlement(body(request), "timeout")
    if not matched:
        logger.warning("Daraja B2C timeout did not match a payment")
    return ok({"success": True})


def update_b2b_bank_settlement(event, callback_status):
    event = event if isinstance(event, dict) else {}
    body_data = event.get("Body") if isinstance(event.get("Body"), dict) else {}
    result = event.get("Result") or body_data.get("Result") or event
    result = result if isinstance(result, dict) else {}
    originator_id = result.get("OriginatorConversationID") or event.get("OriginatorConversationID") or ""
    conversation_id = result.get("ConversationID") or event.get("ConversationID") or ""
    occasion = result.get("Occasion") or event.get("Occasion") or ""
    payment = _find_settlement_payment("daraja_b2b", occasion, originator_id, conversation_id)
    return _apply_settlement_result(payment, result, callback_status) if payment else False


@csrf_exempt
@api_view(["POST"])
def daraja_b2b_result(request):
    matched = update_b2b_bank_settlement(body(request), "result")
    if not matched:
        logger.warning("Daraja B2B bank settlement result did not match a payment")
    return ok({"success": True})


@csrf_exempt
@api_view(["POST"])
def daraja_b2b_timeout(request):
    matched = update_b2b_bank_settlement(body(request), "timeout")
    if not matched:
        logger.warning("Daraja B2B bank settlement timeout did not match a payment")
    return ok({"success": True})
