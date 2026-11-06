import json
import html
import hashlib
import logging
import os
import platform
import re
import secrets
import shutil
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode, urlparse

import jwt
from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.paginator import Paginator
from django.core import signing
from django.db import IntegrityError, close_old_connections, connection
from django.db.utils import DatabaseError, OperationalError
from django.db.models import Count, Sum, Q
from django.db.models.functions import Lower, Trim, Substr
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from billing_api.auth import admin_required, tenant_required
from billing_api.models import AdminAuditLog, AdminUser, Customer, InternetPackage, Payment, RadiusSession, SubscriptionPayment, Tenant, TenantSubscription, Ticket, User
from core.models import Tenant as SchemaTenant
from billing_api.services import (
    admin_token,
    check_password,
    create_hotspot_profile,
    create_ppp_profile,
    configure_router_port,
    selected_daraja_method,
    initiate_daraja_payment,
    make_daraja_callback_token,
    verify_daraja_callback_token,
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

logger = logging.getLogger(__name__)
TENANT_LOGIN_2FA_MAX_AGE_SECONDS = 10 * 60


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


def _normalize_permissions(value):
    return value if isinstance(value, dict) else {}


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


def send_login_verification_email(recipient_email, code):
    if not recipient_email or not code:
        logger.warning("Login verification email skipped because recipient or code is missing")
        return 0
    brand = getattr(settings, "EMAIL_BRAND_NAME", "Expressnet")
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    subject = f"{code} is your {brand} sign-in code"
    text_body = (
        f"Your {brand} sign-in code is {code}.\n\n"
        "Enter this code on the login page to finish signing in. "
        "The code expires in 10 minutes.\n\n"
        "If you did not try to sign in, you can ignore this email."
    )
    html_body = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc;padding:24px 0;">
      <tr><td align="center"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:520px;background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;">
        <tr><td style="padding:28px;">
          <p style="margin:0 0 8px;font-size:14px;font-weight:700;color:#2563eb;">{html.escape(brand)}</p>
          <h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;color:#0f172a;">Sign in verification code</h1>
          <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#334155;">Use this code to finish signing in. It expires in 10 minutes.</p>
          <p style="margin:0 0 22px;padding:14px 18px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;text-align:center;font-size:30px;letter-spacing:8px;font-weight:700;color:#1d4ed8;">{html.escape(code)}</p>
          <p style="margin:0;font-size:13px;line-height:1.5;color:#64748b;">If you did not try to sign in, you can safely ignore this email.</p>
        </td></tr>
      </table></td></tr>
    </table>
  </body>
</html>
"""
    try:
        message = EmailMultiAlternatives(
            subject,
            text_body,
            from_email=from_email,
            to=[recipient_email],
            headers={"Reply-To": from_email} if from_email else None,
        )
        message.attach_alternative(html_body, "text/html")
        sent = message.send(fail_silently=False)
        if not sent:
            logger.warning(
                "Login verification email backend returned 0 sent messages for recipient=%s backend=%s host=%s from=%s",
                recipient_email,
                getattr(settings, "EMAIL_BACKEND", ""),
                getattr(settings, "EMAIL_HOST", ""),
                from_email,
            )
        return sent
    except Exception:
        logger.exception(
            "Failed to send login verification email recipient=%s backend=%s host=%s port=%s user=%s from=%s",
            recipient_email,
            getattr(settings, "EMAIL_BACKEND", ""),
            getattr(settings, "EMAIL_HOST", ""),
            getattr(settings, "EMAIL_PORT", ""),
            getattr(settings, "EMAIL_HOST_USER", ""),
            from_email,
        )
        return 0


def _send_tenant_email_verification(tenant_id, tenant, verification_url):
    recipient = tenant.get("email")
    if not recipient or not verification_url:
        return 0
    brand = getattr(settings, "EMAIL_BRAND_NAME", "Expressnetbilling")
    subject = f"Verify your {brand} account"
    text_body = (
        f"Hello {tenant.get('owner_name') or tenant.get('business_name') or 'there'},\n\n"
        f"Confirm the email address for {tenant.get('business_name') or 'your business'} by opening this link:\n\n"
        f"{verification_url}\n\nThis link expires in 24 hours. After verification, you will be sent to the login page."
    )
    html_body = f"""<!doctype html><html><body style="margin:0;padding:32px 16px;background:#0b1120;font-family:Arial,Helvetica,sans-serif;color:#e2e8f0"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:540px;background:#111c30;border:1px solid #26364e;border-radius:16px"><tr><td style="padding:36px"><p style="margin:0 0 10px;color:#22d3ee;font-size:12px;font-weight:bold;letter-spacing:2px;text-transform:uppercase">{html.escape(brand)}</p><h1 style="margin:0 0 16px;color:#fff;font-size:24px">Verify your email address</h1><p style="margin:0 0 24px;color:#cbd5e1;font-size:15px;line-height:1.6">Confirm this email address to activate sign-in for {html.escape(tenant.get('business_name') or 'your business')}.</p><p style="margin:0 0 28px"><a href="{html.escape(verification_url, quote=True)}" style="display:inline-block;padding:14px 22px;border-radius:10px;background:#06b6d4;color:#082f49;font-weight:bold;text-decoration:none">Verify email</a></p><p style="margin:0;color:#94a3b8;font-size:13px;line-height:1.5">This link expires in 24 hours. After verification, you will be sent to the login page. If you did not create this account, ignore this email.</p></td></tr></table></td></tr></table></body></html>"""
    try:
        message = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [recipient])
        message.attach_alternative(html_body, "text/html")
        return message.send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send tenant verification email tenant=%s email=%s", tenant_id, recipient)
        return 0


def tenant_email_is_verified(tenant):
    """Return the persisted verification state, including older shared-record tenants."""
    if tenant.extra.get("email_verified") is True:
        return True
    try:
        legacy_tenant = ref(f"tenants/{tenant.pk}").get() or {}
    except Exception:
        logger.exception("Could not read email verification state tenant=%s", tenant.pk)
        return False
    if legacy_tenant.get("email_verified") is True:
        tenant.extra["email_verified"] = True
        tenant.save(update_fields=["extra", "updated_at"])
        return True
    # Accounts created before email verification existed must remain usable.
    if "email_verified" not in tenant.extra and "email_verified" not in legacy_tenant:
        return True
    return False
def _tenant_login_challenge_key(challenge_id):
    return f"tenant_login_2fa:{challenge_id}"


def _sign_tenant_login_challenge(challenge):
    return signing.dumps(challenge, salt="tenant-login-2fa")


def _load_tenant_login_challenge(challenge_id):
    challenge_id = str(challenge_id or "").strip()
    if not challenge_id:
        return None
    try:
        challenge = cache.get(_tenant_login_challenge_key(challenge_id))
        if challenge:
            return challenge
    except Exception:
        logger.warning("Tenant login verification cache lookup unavailable", exc_info=True)
    try:
        return signing.loads(
            challenge_id,
            salt="tenant-login-2fa",
            max_age=TENANT_LOGIN_2FA_MAX_AGE_SECONDS,
        )
    except (signing.BadSignature, signing.SignatureExpired):
        return None


def _store_tenant_login_challenge(challenge):
    challenge_id = _sign_tenant_login_challenge(challenge)
    try:
        cache.set(
            _tenant_login_challenge_key(challenge_id),
            challenge,
            timeout=TENANT_LOGIN_2FA_MAX_AGE_SECONDS,
        )
    except Exception:
        logger.warning("Tenant login verification cache storage unavailable", exc_info=True)
    return challenge_id


def _delete_tenant_login_challenge(challenge_id):
    try:
        cache.delete(_tenant_login_challenge_key(challenge_id))
    except Exception:
        logger.warning("Tenant login verification cache cleanup unavailable", exc_info=True)


def _login_failure_key(request, email):
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")).split(",")[0].strip()
    digest = hashlib.sha256(f"{ip}:{email}".encode("utf-8")).hexdigest()
    return f"tenant_login_failures:{digest}"


def _login_failure_response(request, email):
    limit = int(os.getenv("TENANT_LOGIN_FAILURE_LIMIT", "5"))
    window = int(os.getenv("TENANT_LOGIN_FAILURE_WINDOW", str(15 * 60)))
    key = _login_failure_key(request, email)
    try:
        failures = int(cache.get(key) or 0) + 1
        cache.set(key, failures, timeout=window)
    except Exception:
        logger.warning("Tenant login failure rate limit cache unavailable", exc_info=True)
        return None
    if failures > limit:
        return ok({"message": "Too many wrong password attempts. Please try again later."}, 429)
    return None


def _clear_login_failures(request, email):
    try:
        cache.delete(_login_failure_key(request, email))
    except Exception:
        logger.warning("Tenant login failure cache cleanup unavailable", exc_info=True)


def _tenant_login_payload(tenant, member_id=None):
    token = tenant_token(tenant["id"], member_id=member_id)
    if member_id:
        member = (tenant.get("team_members") or {}).get(member_id) or {}
        tenant_payload = {
            "id": tenant["id"],
            "business_name": tenant.get("business_name"),
            "email": member.get("email"),
            "name": member.get("name"),
            "phone": member.get("phone") or "",
            "role": member.get("role") or "",
            "status": member.get("status") or "active",
            "created_at": member.get("created_at") or "",
            "updated_at": member.get("updated_at") or "",
            "member_id": member_id,
            "permissions": _normalize_permissions(member.get("permissions")),
            "is_admin": False,
            **tenant_theme_payload(tenant),
        }
    else:
        tenant_payload = {
            "id": tenant["id"],
            "business_name": tenant.get("business_name"),
            "email": tenant.get("email"),
            "role": "tenant_admin",
            "status": tenant.get("status") or "active",
            "is_admin": True,
            **tenant_theme_payload(tenant),
        }
    return {"success": True, "token": token, "tenant": tenant_payload}


def _password_matches_login(raw_password, stored_password):
    return check_password(raw_password, stored_password)


def _find_staff_login(email, password):
    for tenant_obj in Tenant.objects.filter(status="active"):
        tenant = tenant_obj.as_dict(include_id=True)
        members = tenant.get("team_members") or {}
        if not isinstance(members, dict):
            continue
        for member_id, member in members.items():
            if str(member.get("email") or "").lower().strip() != email:
                continue
            if member.get("status", "active") != "active" or not _password_matches_login(password, member.get("password")):
                return tenant, member_id, member, False
            return tenant, member_id, member, True
    return None, None, None, False


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
    login_url = _tenant_registration_login_url(tenant)
    send_system_email(
        "Your Expressnetbilling account is active",
        (
            f"Hello {tenant.get('owner_name') or tenant.get('business_name')},\n\n"
            f"Your {tenant.get('business_name') or 'Expressnetbilling'} account has been activated. "
            "You can now sign in and finish setting up your workspace.\n\n"
            f"Sign in: {login_url}"
        ),
        [tenant.get("email")],
    )


def tenant_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:48] or f"tenant-{secrets.token_hex(3)}"


def tenant_portal_domain(slug):
    base_domain = str(
        getattr(settings, "TENANT_BASE_DOMAIN", "")
        or os.getenv("TENANT_BASE_DOMAIN")
        or os.getenv("PUBLIC_BASE_DOMAIN")
        or os.getenv("SAAS_PORTAL_HOST")
        or os.getenv("PUBLIC_APP_URL")
        or ""
    ).strip().rstrip("/")
    base_domain = base_domain.replace("https://", "").replace("http://", "").strip("/")
    if not base_domain:
        base_domain = "expressnetbilling.com"
    if "/" in base_domain:
        base_domain = base_domain.split("/", 1)[0]
    return f"{slug}.{base_domain}"


def tenant_portal_url(slug):
    domain = tenant_portal_domain(slug)
    hostname = domain.split(":", 1)[0].lower()
    scheme = "http" if hostname == "localhost" or hostname.endswith(".localhost") else "https"
    return f"{scheme}://{domain}"


def notify_tenant_registered(tenant, request=None):
    workspace_url = _tenant_workspace_url(tenant)
    login_url = workspace_url or (public_base_url(request).rstrip("/") if request else "/")
    send_system_email(
        "Your Expressnetbilling workspace is ready",
        (
            f"Hello {tenant.get('owner_name') or tenant.get('business_name')},\n\n"
            f"Your {tenant.get('business_name') or 'Expressnetbilling'} workspace has been created and is awaiting email verification.\n\n"
            f"Subdomain: {tenant.get('subdomain')}\n"
            f"Workspace URL: {workspace_url}\n"
            "Your account is waiting for email verification. Please use the verification email before attempting to sign in."
        ),
        [tenant.get("email")],
    )


def _tenant_workspace_url(tenant):
    subdomain = str(tenant.get("subdomain") or "").strip()
    if subdomain:
        return tenant_portal_url(subdomain)
    workspace_url = tenant.get("workspace_url") or (f"https://{tenant.get('domain')}" if tenant.get("domain") else "")
    return workspace_url.rstrip("/") if workspace_url else ""


def _tenant_registration_login_url(tenant, fallback=""):
    return _tenant_workspace_url(tenant) or fallback or "/"


def send_tenant_registration_notifications_async(tenant_id, tenant, login_url):
    def _send():
        try:
            notify_admins_tenant_signup(tenant_id, tenant)
            workspace_login_url = _tenant_registration_login_url(tenant, login_url)
            send_system_email(
                "Your Expressnetbilling workspace is ready",
                (
                    f"Hello {tenant.get('owner_name') or tenant.get('business_name')},\n\n"
                    f"Your {tenant.get('business_name') or 'Expressnetbilling'} workspace has been created and is awaiting email verification.\n\n"
                    f"Subdomain: {tenant.get('subdomain')}\n"
                    f"Workspace URL: {workspace_login_url}\n\n"
                    "Your account is waiting for email verification. Please use the verification email before attempting to sign in."
                ),
                [tenant.get("email")],
            )
        except Exception:
            logger.exception("Tenant registration notifications failed for %s", tenant_id)

    threading.Thread(target=_send, daemon=True).start()


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


def normalized_package_payload(data):
    service_type = package_service_type(data or {})
    if service_type not in {"hotspot", "pppoe"}:
        service_type = "hotspot"
    duration_unit = "hours" if str((data or {}).get("duration_unit") or "").lower().startswith("hour") else "days"
    if service_type == "pppoe":
        duration_unit = "days"
    duration_value = float((data or {}).get("duration_value") or (data or {}).get("duration_hours") or (data or {}).get("duration_days") or 1)
    if service_type == "pppoe" and duration_value < 1:
        duration_value = 1
    duration_days = 1 if duration_unit == "hours" else int(duration_value)
    duration_hours = duration_value if duration_unit == "hours" else duration_value * 24
    return {
        "service_type": service_type,
        "duration_unit": duration_unit,
        "duration_value": duration_value,
        "duration_days": duration_days,
        "duration_hours": duration_hours,
    }


def sync_package_profile(tenant, package):
    service_type = package_service_type(package)
    duration_seconds = int(package_duration_delta(package).total_seconds())
    if service_type == "pppoe":
        return create_ppp_profile(tenant, package.get("name"), package.get("speed"), duration_seconds)
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
    trial_days = int(os.getenv("TENANT_TRIAL_DAYS", os.getenv("TENANT_GRACE_PERIOD_DAYS", "14")))
    now = timezone.now()
    subscription, _ = TenantSubscription.objects.get_or_create(
        tenant=tenant,
        defaults={
            "plan": plan if plan in plan_amounts else "basic",
            "amount": plan_amounts.get(plan, 1500),
            "started_at": now,
            "expires_at": now + timedelta(days=trial_days),
            "grace_period_days": trial_days,
            "notes": f"Initial {trial_days}-day trial/grace period",
        },
    )
    return subscription


def subscription_payload(subscription, include_payments=False):
    data = subscription.as_dict()
    if include_payments:
        data["payments"] = [payment.as_dict() for payment in subscription.payments.order_by("-paid_at")]
    return data


def system_subscription_fee_percent():
    try:
        return Decimal(str(os.getenv("SYSTEM_SUBSCRIPTION_FEE_PERCENT", "0.03") or "0.03"))
    except Exception:
        return Decimal("0.03")


def tenant_monthly_internet_sales(tenant):
    month_prefix = timezone.now().strftime("%Y-%m")
    total = Payment.objects.filter(tenant=tenant, status="success", paid_at__startswith=month_prefix).aggregate(total=Sum("amount"))["total"]
    return Decimal(str(total or 0))


def system_subscription_amount(tenant):
    sales = tenant_monthly_internet_sales(tenant)
    percent = system_subscription_fee_percent()
    amount = (sales * percent / Decimal("100")).quantize(Decimal("0.01"))
    return amount, sales, percent


def tenant_subscription_payload(subscription):
    amount, sales, percent = system_subscription_amount(subscription.tenant)
    data = subscription_payload(subscription)
    data["amount"] = float(amount)
    data["system_fee_percent"] = float(percent)
    data["system_fee_sales_basis"] = float(sales)
    data["system_fee_period"] = timezone.now().strftime("%Y-%m")
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
        ref(f"tenants/{subscription.tenant_id}").update(
            {
                "status": "active",
                "subscription_restored_at": iso_now(),
                "suspended_reason": "",
                "updated_at": iso_now(),
            }
        )
    return payment


@csrf_exempt
@api_view(["GET", "POST"])
@tenant_required
def tenant_subscription_status(request):
    tenant = Tenant.objects.filter(pk=request.tenant["id"]).first()
    if not tenant:
        return ok({"message": "Tenant not found"}, 404)
    subscription = ensure_subscription(tenant)
    if method(request, "GET"):
        site_settings = ref("site_settings").get() or {}
        payment_destination = {
            "bank_name": str(site_settings.get("subscription_bank_name") or "").strip(),
            "account_name": str(site_settings.get("subscription_bank_account_name") or "").strip(),
            "account_number": str(site_settings.get("subscription_bank_account_number") or "").strip(),
            "branch": str(site_settings.get("subscription_bank_branch") or "").strip(),
            "instructions": str(site_settings.get("subscription_payment_instructions") or "").strip(),
        }
        if not payment_destination["bank_name"] and not payment_destination["account_number"]:
            payment_destination = None
        return ok({"subscription": tenant_subscription_payload(subscription), "payment_required": subscription.is_expired() or tenant.status == "suspended", "payment_destination": payment_destination})
    data = body(request)
    if str(data.get("method") or "").lower() == "paystack" or str(data.get("provider") or "").lower() == "paystack":
        return ok({"message": "Paystack payments are temporarily unavailable. Use M-Pesa or submit a bank transfer reference."}, 410)
    if data.get("method") == "mpesa_stk":
        phone = str(data.get("phone") or "").strip()
        if not phone:
            return ok({"message": "Phone number is required"}, 400)
        amount, sales, percent = system_subscription_amount(tenant)
        if amount <= 0:
            return ok({"message": "No system fee is due because this tenant has no successful internet sales for the current month."}, 400)
        tenant_payload = {"id": str(tenant.pk), "business_name": tenant.business_name}
        payment_id = f"system-subscription-{subscription.pk}-{secrets.token_hex(6)}"
        try:
            checkout = initiate_daraja_payment(
                tenant_payload,
                payment_id,
                amount,
                phone,
                description="System renewal",
                metadata={"subscription_id": str(subscription.pk), "sales_basis": str(sales), "fee_percent": str(percent)},
                payment_method=data.get("payment_method") or "daraja_paybill",
            )
        except PaymentProviderError as exc:
            return ok({"message": exc.public_message}, getattr(exc, "status_code", 400) or 400)
        except Exception as exc:
            logger.exception("System subscription STK failed tenant=%s subscription=%s", tenant.pk, subscription.pk)
            return ok({"message": str(exc) or "Could not start M-Pesa payment"}, 502)
        return ok(
            {
                "success": True,
                "message": checkout.get("customer_message") or "STK push sent. Complete payment on your phone.",
                "checkout": checkout,
                "payment_id": payment_id,
                "subscription": tenant_subscription_payload(subscription),
            }
        )
    if str(data.get("provider") or "").lower() == "paystack":
        return ok({"message": "Paystack payments are temporarily unavailable. Use M-Pesa or submit a bank transfer reference."}, 410)
    reference = str(data.get("reference") or "").strip()
    if not reference:
        return ok({"message": "Payment reference is required"}, 400)
    payment = record_subscription_payment(subscription, {**data, "method": data.get("method") or "manual"}, "")
    return ok({"success": True, "message": "Payment submitted", "payment": payment.as_dict(), "subscription": tenant_subscription_payload(subscription)})


def react_app(request):
    index = Path(settings.BASE_DIR) / "frontend" / "dist" / "index.html"
    if not index.exists():
        raise Http404("Build the React app first with npm --prefix frontend run build")
    response = FileResponse(index.open("rb"), content_type="text/html")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


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

    candidates = [getattr(settings, "PUBLIC_APP_URL", ""), os.getenv("PUBLIC_APP_URL")]
    if settings.DEBUG:
        candidates = [request_url]
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
        "bank_code": tenant.get("bank_code") or "",
        "bank_name": tenant.get("bank_name") or "",
        "bank_account_number": tenant.get("bank_account_number") or "",
        "payment_methods": tenant.get("payment_methods") if isinstance(tenant.get("payment_methods"), list) else ["bank"],
        "has_daraja_consumer_key": bool(tenant.get("daraja_consumer_key")),
        "has_daraja_consumer_secret": bool(tenant.get("daraja_consumer_secret")),
        "daraja_shortcode": tenant.get("daraja_shortcode") or "",
        "has_daraja_passkey": bool(tenant.get("daraja_passkey")),
        "daraja_till_number": tenant.get("daraja_till_number") or "",
        "daraja_shortcode_type": tenant.get("daraja_shortcode_type") or "CustomerBuyGoodsOnline",
        "daraja_environment": tenant.get("daraja_environment") or "production",
    }



@csrf_exempt
@api_view(["GET"])
def health(request):
    checks = health_payload()
    return ok(
        {
            "ok": True,
            "service": "billing-saas-django",
            "cronEnabled": os.getenv("ENABLE_CRON") == "true",
            "config": {
                "nodeEnv": os.getenv("NODE_ENV", "development"),
                "databaseEngine": settings.DATABASES["default"]["ENGINE"],
                "databaseName": str(settings.DATABASES["default"]["NAME"]),
                "jwtSecretSet": bool(os.getenv("JWT_SECRET")),
                "adminJwtSecretSet": bool(os.getenv("ADMIN_JWT_SECRET")),
            },
            **checks,
        }
    )


def _business_name_exists(name, exclude_tenant_id=None, exclude_email=None):
    normalized = str(name or "").strip().lower()
    billing_tenants = Tenant.objects.annotate(normalized_business=Lower(Trim("business_name"))).filter(normalized_business=normalized)
    if exclude_tenant_id is not None:
        billing_tenants = billing_tenants.exclude(pk=exclude_tenant_id)
    if exclude_email:
        billing_tenants = billing_tenants.exclude(email__iexact=exclude_email)
    schema_tenants = SchemaTenant.objects.annotate(normalized_business=Lower(Trim("business_name"))).filter(normalized_business=normalized)
    if exclude_tenant_id is not None:
        schema_tenants = schema_tenants.exclude(pk=exclude_tenant_id)
    if exclude_email:
        schema_tenants = schema_tenants.exclude(email__iexact=exclude_email)
    return billing_tenants.exists() or schema_tenants.exists()


@csrf_exempt
@api_view(["POST"])
def auth_register(request):
    data = body(request)
    missing = [field for field in ["business_name", "owner_name", "email", "phone", "password"] if not data.get(field)]
    if missing:
        return ok({"message": f"Missing fields: {', '.join(missing)}"}, 400)
    email = data["email"].lower().strip()
    confirmation = str(data.get("confirm_password") or data.get("password_confirmation") or "")
    if confirmation and confirmation != str(data.get("password") or ""):
        return ok({"message": "Passwords do not match."}, 400)
    business_name = str(data["business_name"]).strip()
    if not business_name:
        return ok({"message": "Business name is required"}, 400)
    if _business_name_exists(business_name, exclude_email=email):
        return ok({"message": "A business with this name is already registered. Choose a different business name."}, 409)
    existing_tenant = Tenant.objects.filter(email__iexact=email).first()
    if existing_tenant and check_password(data["password"], existing_tenant.password):
        ensure_subscription(existing_tenant, data.get("plan") or "basic")
        verification_required = bool(getattr(settings, "TENANT_EMAIL_VERIFICATION_REQUIRED", False))
        return ok(
            {
                "success": True,
                "message": (
                    "This email is already registered. Check your inbox for the email verification link before signing in."
                    if verification_required
                    else "This email is already registered. Email verification is temporarily disabled; you can sign in now."
                ),
                "tenantId": str(existing_tenant.pk),
            }
        )
    if existing_tenant:
        return ok({"message": "Email already registered"}, 400)
    base_slug = tenant_slug(business_name)
    slug = base_slug
    suffix = 2
    while Tenant.objects.filter(extra__subdomain=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    workspace_url = tenant_portal_url(slug)

    try:
        tenant_ref = ref("tenants").push(
            {
                "business_name": business_name,
                "owner_name": data["owner_name"],
                "email": email,
                "phone": data["phone"],
                "subdomain": slug,
                "domain": tenant_portal_domain(slug),
                "workspace_url": workspace_url,
                "password": hash_password(data["password"]),
                "business_number": str(data.get("business_number") or "").strip(),
                "bank_code": str(data.get("bank_code") or "").strip(),
                "bank_name": str(data.get("bank_name") or "").strip(),
                "bank_account_number": str(data.get("bank_account_number") or "").strip(),
                "mikrotik_host": "",
                "mikrotik_user": "",
                "mikrotik_pass": "",
                "mikrotik_port": 8728,
                "sms_balance": 10,
                "sms_sent_count": 0,
                "theme_color": data.get("theme_color") or "#fa8200",
                "dark_mode": False,
                "status": "active",
                "email_verified": False,
                "email_verification_token": "",
                "created_at": iso_now(),
            }
        )
    except IntegrityError as exc:
        if "business_name" in str(exc).lower():
            return ok({"message": "A business with this name is already registered. Choose a different business name."}, 409)
        if "email" in str(exc).lower() or "unique" in str(exc).lower():
            logger.info("Tenant registration duplicate email race for %s", email)
            return ok({"message": "Email already registered"}, 400)
        # Database/migration details are operational diagnostics, not public
        # registration feedback. They remain in the protected server/admin
        # diagnostics, while tenants receive a safe, actionable response.
        logger.exception("Tenant registration database constraint failed for %s; inspect migrations in the admin system view", email)
        return ok({
            "message": "We could not create your account right now. Please try again shortly.",
            "code": "REGISTRATION_TEMPORARILY_UNAVAILABLE",
        }, 500)
    except Exception:
        logger.exception("Tenant registration failed for %s", email)
        return ok({"message": "Registration failed. Please try again or contact support."}, 500)
    tenant_data = ref(f"tenants/{tenant_ref.key}").get() or {}
    verification_required = bool(getattr(settings, "TENANT_EMAIL_VERIFICATION_REQUIRED", False))
    verification_token = signing.dumps(
        {"tenant_id": str(tenant_ref.key), "email": email},
        salt="tenant-email-verification",
    ) if verification_required else ""
    tenant_data["email_verified"] = not verification_required
    tenant_data["email_verification_token"] = verification_token
    ref(f"tenants/{tenant_ref.key}").update({
        "email_verified": not verification_required,
        "email_verification_token": verification_token or None,
    })
    tenant_instance = Tenant.objects.filter(pk=tenant_ref.key).first()
    if tenant_instance:
        tenant_instance.extra["email_verified"] = not verification_required
        if verification_token:
            tenant_instance.extra["email_verification_token"] = verification_token
        else:
            tenant_instance.extra.pop("email_verification_token", None)
        tenant_instance.save(update_fields=["extra", "updated_at"])
        ensure_subscription(tenant_instance, data.get("plan") or "basic")
    verification_url = f"{public_base_url(request).rstrip('/')}/{settings.API_BASE_PATH}/v1/core/auth/verify-email?token={verification_token}" if verification_token else ""
    login_url = workspace_url.rstrip("/")
    send_tenant_registration_notifications_async(tenant_ref.key, tenant_data, login_url)
    if verification_required and not _send_tenant_email_verification(tenant_ref.key, tenant_data, verification_url):
        ref(f"tenants/{tenant_ref.key}").update({"email_verification_token": None})
        tenant_instance = Tenant.objects.filter(pk=tenant_ref.key).first()
        if tenant_instance:
            tenant_instance.extra["email_verification_token"] = ""
            tenant_instance.save(update_fields=["extra", "updated_at"])
        return ok({"message": "Your account was created, but we could not send the verification email. Please contact support to resend it."}, 502)
    message = (
        "Your account was created. Check your email and open the verification link to continue to sign in."
        if verification_required
        else "Your account was created. Email verification is temporarily disabled; you can sign in now."
    )
    return ok({"success": True, "message": message, "tenantId": tenant_ref.key, "subdomain": tenant_data.get("subdomain"), "domain": tenant_data.get("domain"), "workspaceUrl": tenant_data.get("workspace_url")})


@csrf_exempt
@api_view(["GET"])
@permission_classes([AllowAny])
def auth_verify_email(request):
    token = str(request.query_params.get("token") or "").strip()
    if not token:
        return redirect(f"{settings.PUBLIC_APP_URL.rstrip('/')}/login?verification=missing")
    try:
        verification = signing.loads(token, salt="tenant-email-verification", max_age=24 * 60 * 60)
    except (signing.BadSignature, signing.SignatureExpired):
        return redirect(f"{settings.PUBLIC_APP_URL.rstrip('/')}/login?verification=invalid")
    tenant = Tenant.objects.filter(pk=verification.get("tenant_id"), email__iexact=verification.get("email", "")).first()
    if not tenant:
        return redirect(f"{settings.PUBLIC_APP_URL.rstrip('/')}/login?verification=invalid")
    workspace_url = _tenant_workspace_url({**tenant.as_dict(), **tenant.extra})
    local_verification_host = request.get_host().split(":", 1)[0].lower() in {"localhost", "127.0.0.1", "[::1]"}
    if settings.DEBUG and local_verification_host:
        login_url = f"{public_base_url(request).rstrip('/')}/login"
    else:
        login_url = f"{workspace_url}/login" if workspace_url else f"{public_base_url(request).rstrip('/')}/login"
    if tenant_email_is_verified(tenant):
        return redirect(f"{login_url}?email_verified=1")
    tenant.extra["email_verified"] = True
    tenant.extra.pop("email_verification_token", None)
    tenant.save(update_fields=["extra", "updated_at"])
    try:
        ref(f"tenants/{tenant.pk}").update({"email_verified": True, "email_verification_token": None})
    except Exception:
        logger.exception("Failed to sync tenant email verification to tenant record tenant=%s", tenant.pk)
    cache.delete(f"tenant_auth:{tenant.pk}")
    return redirect(f"{login_url}?email_verified=1")


@csrf_exempt
@api_view(["POST"])
def auth_login(request):
    data = body(request)
    if data.get("resend_challenge_id"):
        challenge_id = str(data.get("resend_challenge_id") or "").strip()
        challenge = _load_tenant_login_challenge(challenge_id)
        if not challenge:
            return ok({"message": "Invalid or expired verification code"}, 401)
        sent = send_login_verification_email(challenge.get("email"), challenge.get("code"))
        if not sent:
            return ok({"message": "We could not resend the verification email. Please try again."}, 502)
        return ok({"success": True, "message": "Verification code resent to your email."})

    if data.get("challenge_id"):
        challenge_id = str(data.get("challenge_id") or "").strip()
        code = "".join(ch for ch in str(data.get("code") or "") if ch.isdigit())
        challenge = _load_tenant_login_challenge(challenge_id)
        if not challenge or not code or code != str(challenge.get("code")):
            return ok({"message": "Invalid or expired verification code"}, 401)
        _delete_tenant_login_challenge(challenge_id)
        tenant_obj = Tenant.objects.filter(pk=challenge.get("tenant_id")).first()
        if not tenant_obj:
            return ok({"message": "Tenant not found"}, 401)
        tenant = tenant_obj.as_dict(include_id=True)
        member_id = challenge.get("member_id")
        try:
            return ok(_tenant_login_payload(tenant, member_id=member_id))
        except Exception as exc:
            return ok({"message": f"Server configuration error: {exc}"}, 500)

    if not data.get("email") or not data.get("password"):
        return ok({"message": "Email and password are required"}, 400)
    email = str(data["email"]).lower().strip()
    password = str(data["password"]).strip()

    registered_tenant = Tenant.objects.filter(email__iexact=email).first()
    if (
        registered_tenant
        and getattr(settings, "TENANT_EMAIL_VERIFICATION_REQUIRED", False)
        and not tenant_email_is_verified(registered_tenant)
    ):
        return ok({"message": "Verify your email address using the link we sent before signing in."}, 403)

    def complete_login(tenant, member_id=None):
        try:
            return ok(_tenant_login_payload(tenant, member_id=member_id))
        except Exception as exc:
            return ok({"message": f"Server configuration error: {exc}"}, 500)

    tenant_obj = Tenant.objects.filter(email__iexact=email).first()
    if tenant_obj:
        if not _password_matches_login(password, tenant_obj.password):
            staff_tenant, member_id, member, staff_password_ok = _find_staff_login(email, password)
            if staff_tenant and staff_password_ok:
                _clear_login_failures(request, email)
                return complete_login(staff_tenant, member_id=member_id)
            limited = _login_failure_response(request, email)
            if limited:
                return limited
            return ok({"message": "Wrong password"}, 401)
        _clear_login_failures(request, email)
        tenant = tenant_obj.as_dict(include_id=True)
        if tenant.get("status") not in {"active", "suspended"}:
            tenant_obj.status = "active"
            tenant_obj.save(update_fields=["status"])
            tenant["status"] = "active"
        return complete_login(tenant)

    staff_tenant, member_id, member, staff_password_ok = _find_staff_login(email, password)
    if staff_tenant:
        if not staff_password_ok:
            limited = _login_failure_response(request, email)
            if limited:
                return limited
            return ok({"message": "Wrong password"}, 401)
        _clear_login_failures(request, email)
        return complete_login(staff_tenant, member_id=member_id)

    limited = _login_failure_response(request, email)
    if limited:
        return limited
    return ok({"message": "Account not found"}, 404)


@csrf_exempt
@api_view(["GET"])
def public_site(request):
    return ok({**DEFAULT_SITE, **(ref("site_settings").get() or {})})


@csrf_exempt
@api_view(["GET"])
def public_stats(request):
    tenants = list_children("tenants")
    active_tenants = [tenant for tenant in tenants if tenant.get("status") == "active"]
    customers = []
    for tenant in tenants:
        customers.extend(list_children(f"tenants/{tenant['id']}/customers"))
    active_customers = [customer for customer in customers if customer.get("status") == "active"]
    return ok(
        {
            "totalTenants": len(tenants),
            "activeTenants": len(active_tenants),
            "totalCustomers": len(customers),
            "activeCustomers": len(active_customers),
        }
    )




@csrf_exempt
@api_view(["POST"])
def admin_login(request):
    data = body(request)
    if not data.get("email") or not data.get("password"):
        return ok({"error": "Email and password required"}, 400)
    email = str(data["email"]).lower().strip()
    password = data["password"]
    admin = find_child_by_field("admins", "email", email)

    if admin and admin.get("is_active") and check_password(password, admin.get("password")):
        login_count = int(admin.get("login_count") or 0) + 1
        ref(f"admins/{admin['id']}").update({"last_login": iso_now(), "login_count": login_count})
        write_audit_log(admin["id"], admin.get("email"), "LOGIN", admin["id"], "admin", request, {"login_count": login_count})
        try:
            token = admin_token(admin["id"], admin)
        except Exception as exc:
            return ok({"error": f"Server configuration error: {exc}"}, 500)
        return ok({"token": token, "admin": {"id": admin["id"], "name": admin.get("name"), "email": admin.get("email"), "role": admin.get("role")}})

    user = User.objects.filter(email__iexact=email).first()
    if not user or not user.is_active or not user.check_password(password):
        return ok({"error": "Invalid credentials"}, 401)
    if not (user.is_superuser or user.is_staff or user.role == User.Role.ADMIN):
        return ok({"error": "Insufficient privileges"}, 403)

    admin_profile = AdminUser.objects.filter(user=user).first() or AdminUser.objects.filter(email__iexact=email).first()
    if not admin_profile:
        admin_profile = AdminUser(user=user, name=user.name, email=user.email, password="", role="admin", is_active=True)
    admin_profile.user = user
    admin_profile.name = admin_profile.name or user.name
    admin_profile.email = user.email
    admin_profile.role = "admin"
    admin_profile.is_active = True
    admin_profile.last_login = iso_now()
    admin_profile.login_count = int(admin_profile.login_count or 0) + 1
    admin_profile.save()

    admin = admin_profile.as_dict()
    admin["id"] = str(admin_profile.pk)
    write_audit_log(admin["id"], admin.get("email"), "LOGIN", admin["id"], "admin", request, {"login_count": admin_profile.login_count})
    try:
        token = admin_token(admin["id"], admin)
    except Exception as exc:
        return ok({"error": f"Server configuration error: {exc}"}, 500)
    return ok({"token": token, "admin": {"id": admin["id"], "name": admin.get("name"), "email": admin.get("email"), "role": admin.get("role")}})


def mask_tenant(tenant):
    return {key: (MASKED if key in SENSITIVE_FIELDS and value else value) for key, value in tenant.items()}


def tenant_admin_payload(tenant):
    tenant_id = tenant.get("id")
    instance = Tenant.objects.filter(pk=tenant_id).first()
    subscription = ensure_subscription(instance) if instance else None
    payload = {"id": tenant_id, **mask_tenant(tenant)}
    payload["subscription"] = subscription_payload(subscription) if subscription else None
    month_prefix = timezone.now().strftime("%Y-%m")
    month_sales = Payment.objects.filter(tenant_id=tenant_id, status__iexact="success", paid_at__startswith=month_prefix).aggregate(total=Sum("amount"))["total"] or 0
    payload["monthly_revenue"] = float(month_sales)
    payload["onboarding"] = {
        "mikrotik": bool(tenant.get("mikrotik_host") and tenant.get("mikrotik_user")),
        "customers": len(list_children(f"tenants/{tenant_id}/customers")) > 0,
        "packages": len(list_children(f"tenants/{tenant_id}/packages")) > 0,
    }
    return payload


def tenant_overview_payload(tenant_id):
    counts = {str(row["service_type"]).lower(): row["total"] for row in Customer.objects.filter(tenant_id=tenant_id).values("service_type").annotate(total=Count("id"))}
    now = timezone.now()
    tenant = Tenant.objects.filter(pk=tenant_id).first()
    tenant_data = tenant.as_dict() if tenant else {}
    today_prefix = now.date().isoformat()
    month_prefix = now.strftime("%Y-%m")
    successful_payments = Payment.objects.filter(tenant_id=tenant_id, status__iexact="success")
    revenue_today = float(successful_payments.filter(paid_at__startswith=today_prefix).aggregate(total=Sum("amount"))["total"] or 0)
    revenue_this_month = float(successful_payments.filter(paid_at__startswith=month_prefix).aggregate(total=Sum("amount"))["total"] or 0)
    system_fee_due, fee_sales_basis, fee_percent = system_subscription_amount(tenant) if tenant else (Decimal("0"), Decimal("0"), system_subscription_fee_percent())
    subscription = TenantSubscription.objects.filter(tenant_id=tenant_id).first()
    linked = tenant_data.get("linked_routers") or {}
    linked_items = list(linked.items()) if isinstance(linked, dict) else list(enumerate(linked)) if isinstance(linked, list) else []
    routers = []
    for router_id, router in linked_items:
        router = router if isinstance(router, dict) else {"name": str(router)}
        routers.append({
            "id": str(router_id),
            "name": str(router.get("name") or router.get("router_name") or router.get("label") or f"Router {router_id}"),
            "host": str(router.get("host") or router.get("ip") or router.get("address") or ""),
            "port": router.get("port") or router.get("api_port") or "",
            "model": str(router.get("model") or router.get("board_name") or ""),
            "status": str(router.get("status") or router.get("connection_status") or "configured"),
        })
    if not routers and tenant_data.get("mikrotik_host"):
        routers = [{
            "id": "primary",
            "name": str(tenant_data.get("mikrotik_detected_board") or "Primary MikroTik"),
            "host": str(tenant_data.get("mikrotik_host") or ""),
            "port": tenant_data.get("mikrotik_port") or 8728,
            "model": str(tenant_data.get("mikrotik_detected_board") or ""),
            "status": str(tenant_data.get("mikrotik_provisioning_status") or "configured"),
        }]
    snapshot = tenant_data.get("mikrotik_router_snapshot") or {}
    snapshot_sessions = snapshot.get("active_sessions") if isinstance(snapshot, dict) else {}
    snapshot_session_count = int(snapshot_sessions.get("total") or 0) if isinstance(snapshot_sessions, dict) else 0
    radius_session_count = RadiusSession.objects.filter(tenant_id=tenant_id, stopped_at__isnull=True).count()
    last_seen = parse_date(tenant_data.get("mikrotik_last_seen_at"))
    if last_seen and timezone.is_naive(last_seen):
        last_seen = timezone.make_aware(last_seen, timezone.get_current_timezone())
    router_status = "online" if last_seen and now - last_seen <= timedelta(minutes=3) else "offline" if tenant_data.get("mikrotik_host") or linked_items else "not configured"
    month_start = now.date().replace(day=1)
    six_month_start = (month_start - timedelta(days=155)).replace(day=1)
    monthly_rows = Payment.objects.filter(
        tenant_id=tenant_id,
        status__iexact="success",
        paid_at__gte=six_month_start.isoformat(),
    ).annotate(month=Substr("paid_at", 1, 7)).values("month").annotate(total=Sum("amount"))
    by_month = {row["month"]: float(row["total"] or 0) for row in monthly_rows}
    month_keys = []
    cursor = month_start
    for _ in range(6):
        month_keys.append(cursor.strftime("%Y-%m"))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    month_keys.reverse()
    monthly_amounts = [{"month": key, "amount": round(by_month.get(key, 0), 2)} for key in month_keys]
    return {
        "pppoeCustomers": counts.get("pppoe", 0),
        "hotspotUsers": counts.get("hotspot", 0),
        "totalCustomers": sum(counts.values()),
        "routerCount": len(routers),
        "activeSessions": max(radius_session_count, snapshot_session_count),
        "revenueToday": round(revenue_today, 2),
        "revenueThisMonth": round(revenue_this_month, 2),
        "systemFeeDue": round(float(system_fee_due), 2),
        "systemFeePercent": float(fee_percent),
        "systemFeeSalesBasis": round(float(fee_sales_basis), 2),
        "systemFeeCurrency": (subscription.currency if subscription else "KES") or "KES",
        "systemFeePeriod": month_prefix,
        "network": {
            "status": router_status,
            "host": str(tenant_data.get("mikrotik_host") or ""),
            "username": str(tenant_data.get("mikrotik_user") or ""),
            "port": tenant_data.get("mikrotik_port") or 8728,
            "provisioningStatus": str(tenant_data.get("mikrotik_provisioning_status") or ""),
            "lastSeenAt": tenant_data.get("mikrotik_last_seen_at") or "",
            "radiusEnabled": bool(tenant_data.get("radius_enabled")),
            "routers": routers,
            "activeSessions": max(radius_session_count, snapshot_session_count),
            "sessionSource": "router snapshot and RADIUS" if snapshot_session_count and radius_session_count else "router snapshot" if snapshot_session_count else "RADIUS accounting" if radius_session_count else "No active session records",
        },
        "averageMonthlyRevenue": round(sum(item["amount"] for item in monthly_amounts) / 6, 2),
        "revenueByMonth": monthly_amounts,
        "revenueWindowMonths": 6,
    }


@csrf_exempt
@api_view(["GET", "POST", "PATCH", "DELETE"])
@admin_required
def admin_tenants(request, tenant_id=None, child=None):
    if tenant_id and child == "customers":
        return ok(list_children(f"tenants/{tenant_id}/customers"))
    if tenant_id and child == "payments":
        return ok(list_children(f"tenants/{tenant_id}/payments"))
    if tenant_id and child == "packages":
        return ok(list_children(f"tenants/{tenant_id}/packages"))
    if tenant_id and child == "audit" and method(request, "GET"):
        tenant_filter = Q(tenant_id=str(tenant_id)) | Q(target_type="tenant", target_id=str(tenant_id))
        try:
            records = list(
                AdminAuditLog.objects.filter(
                    tenant_filter | Q(metadata__tenantId=str(tenant_id))
                ).order_by("-timestamp")[:500]
            )
        except DatabaseError:
            logger.exception("Tenant audit metadata query failed tenant=%s; using indexed audit fields", tenant_id)
            records = list(AdminAuditLog.objects.filter(tenant_filter).order_by("-timestamp")[:500])
        return ok([item.as_dict() for item in records])
    if tenant_id and child == "overview" and method(request, "GET"):
        if not Tenant.objects.filter(pk=tenant_id).exists():
            return ok({"error": "Tenant not found"}, 404)
        return ok(tenant_overview_payload(tenant_id))
    if method(request, "GET") and not tenant_id:
        tenants = [tenant_admin_payload(item) for item in list_children("tenants")]
        write_audit_log(request.admin["adminId"], request.admin["email"], "LIST_TENANTS", target_type="tenant", request=request, metadata={"count": len(tenants)})
        return ok(tenants)
    if method(request, "GET") and tenant_id:
        tenant = ref(f"tenants/{tenant_id}").get()
        if not tenant:
            return ok({"error": "Tenant not found"}, 404)
        return ok(tenant_admin_payload({"id": tenant_id, **tenant}))
    if method(request, "POST") and not tenant_id:
        data = body(request)
        required = ["business_name", "owner_name", "email", "phone", "password", "mikrotik_host", "mikrotik_user", "mikrotik_pass"]
        missing = [field for field in required if not data.get(field)]
        if missing:
            return ok({"error": f"Missing fields: {', '.join(missing)}"}, 400)
        if find_child_by_field("tenants", "email", data["email"]):
            return ok({"error": "Email already registered"}, 409)
        business_name = str(data["business_name"]).strip()
        if not business_name:
            return ok({"error": "Business name is required"}, 400)
        if _business_name_exists(business_name):
            return ok({"error": "A business with this name already exists"}, 409)
        new_ref = ref("tenants").push({**{field: data.get(field) for field in required if field != "password"}, "business_name": business_name, "email": data["email"].lower().strip(), "password": hash_password(data["password"]), "mikrotik_port": int(data.get("mikrotik_port") or 8728), "status": "active", "created_by": f"admin:{request.admin['adminId']}", "created_at": iso_now()})
        tenant_instance = Tenant.objects.get(pk=new_ref.key)
        ensure_subscription(tenant_instance, data.get("plan") or "basic")
        write_audit_log(request.admin["adminId"], request.admin["email"], "CREATE_TENANT", new_ref.key, "tenant", request, {"business_name": data["business_name"], "email": data["email"].lower().strip()}, tenant_id=new_ref.key)
        return ok({"message": "Tenant created", "tenantId": new_ref.key}, 201)
    if method(request, "PATCH") and tenant_id:
        data = body(request)
        existing_tenant = ref(f"tenants/{tenant_id}").get() or {}
        if "password" in data:
            return ok({"error": "Cannot update sensitive fields via this route: password"}, 400)
        allowed = ["business_name", "owner_name", "email", "phone", "mikrotik_host", "mikrotik_user", "mikrotik_pass", "mikrotik_port", "status"]
        updates = {}
        for field in allowed:
            if field in data:
                value = data[field]
                if field in {"mikrotik_pass", } and (not str(value).strip() or value == MASKED):
                    continue
                updates[field] = value
        if "email" in updates:
            updates["email"] = str(updates["email"]).lower().strip()
        if "business_name" in updates:
            updates["business_name"] = str(updates["business_name"]).strip()
            current_name = str(existing_tenant.get("business_name") or "").strip()
            if updates["business_name"].lower() != current_name.lower() and _business_name_exists(updates["business_name"], exclude_tenant_id=tenant_id):
                return ok({"error": "A business with this name already exists"}, 409)
        if "mikrotik_port" in updates:
            updates["mikrotik_port"] = int(updates["mikrotik_port"] or 8728)
        if not updates:
            return ok({"error": "No allowed fields provided"}, 400)
        try:
            ref(f"tenants/{tenant_id}").update(updates)
        except IntegrityError:
            if "business_name" in updates:
                return ok({"error": "A business with this name already exists"}, 409)
            raise
        if updates.get("status") == "active" and existing_tenant.get("status") != "active":
            notify_tenant_activated({**existing_tenant, **updates, "id": tenant_id})
        if data.get("plan"):
            tenant_instance = Tenant.objects.filter(pk=tenant_id).first()
            if tenant_instance:
                subscription = ensure_subscription(tenant_instance, data.get("plan"))
                subscription.plan = data.get("plan")
                subscription.save(update_fields=["plan", "updated_at"])
        write_audit_log(request.admin["adminId"], request.admin["email"], "UPDATE_TENANT", tenant_id, "tenant", request, {"updated_fields": list(updates)}, tenant_id=tenant_id)
        return ok({"message": "Tenant updated"})
    if method(request, "DELETE") and tenant_id:
        tenant = Tenant.objects.filter(pk=tenant_id).first()
        if not tenant:
            return ok({"error": "Tenant not found"}, 404)
        business_name = tenant.business_name
        write_audit_log(request.admin["adminId"], request.admin["email"], "DELETE_TENANT", tenant_id, "tenant", request, {"business_name": business_name}, tenant_id=tenant_id)
        tenant.delete()
        cache.delete(f"tenant_auth:{tenant_id}")
        return ok({"message": "Tenant deleted"})
    return ok({"message": " Method not allowed "}, 405)


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_stats(request):
    return admin_system_stats(request)


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_system_stats(request):
    now = timezone.now()
    today = now.date()
    month_payments = SubscriptionPayment.objects.filter(paid_at__year=now.year, paid_at__month=now.month).aggregate(total=Sum("amount"))["total"] or 0
    payments_today = Payment.objects.filter(paid_at__startswith=today.isoformat()).aggregate(total=Sum("amount"))["total"] or 0
    tenants_qs = Tenant.objects.all()
    top_tenants = []
    for tenant in tenants_qs:
        top_tenants.append({"id": str(tenant.pk), "business_name": tenant.business_name, "customer_count": Customer.objects.filter(tenant=tenant).count()})
    top_tenants = sorted(top_tenants, key=lambda item: item["customer_count"], reverse=True)[:5]
    return ok(
        {
            "totalTenants": tenants_qs.count(),
            "activeTenants": tenants_qs.filter(status="active").count(),
            "suspendedTenants": tenants_qs.filter(status="suspended").count(),
            "pendingTenants": tenants_qs.filter(status="pending_setup").count(),
            "totalCustomers": Customer.objects.count(),
            "paymentsToday": float(payments_today or 0),
            "monthlyRevenue": float(month_payments or 0),
            "expiringThisWeek": TenantSubscription.objects.filter(expires_at__lte=now + timedelta(days=7), expires_at__gte=now).count(),
            "expiredCount": TenantSubscription.objects.filter(expires_at__lt=now).count(),
            "systemHealth": health_payload(),
            "topTenants": top_tenants,
        }
    )


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_system_metrics(request):
    """Return live host/container and backing-service metrics for admin monitoring."""
    from django.conf import settings as django_settings

    sampled_at = timezone.now()
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count() or 1
        memory = psutil.virtual_memory()
        memory_used = int(memory.used)
        memory_total = int(memory.total)
        process = psutil.Process(os.getpid())
        process_rss = int(process.memory_info().rss)
        system_uptime = max(0, int(time.time() - psutil.boot_time()))
        process_uptime = max(0, int(time.time() - process.create_time()))
    except ImportError:
        cpu_percent = None
        cpu_count = os.cpu_count() or 1
        memory_used = memory_total = process_rss = system_uptime = process_uptime = None
    load_average = None
    try:
        load_average = list(os.getloadavg())
    except (AttributeError, OSError):
        pass

    # Prefer the container's memory cgroup limit where available (e.g. Railway/Docker).
    for current_path, limit_path in (
        ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
        ("/sys/fs/cgroup/memory/memory.usage_in_bytes", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        try:
            current_value = int(Path(current_path).read_text().strip())
            limit_text = Path(limit_path).read_text().strip()
            limit_value = int(limit_text)
            if memory_total and limit_value > 0 and limit_value < memory_total * 10:
                memory_used, memory_total = current_value, limit_value
                break
        except (OSError, ValueError):
            continue

    disk = shutil.disk_usage(os.path.abspath(os.sep))
    database = {"status": "unknown", "latencyMs": None, "engine": connection.vendor, "connections": None, "maxConnections": None, "sizeBytes": None}
    start = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            if connection.vendor == "postgresql":
                cursor.execute("SELECT pg_database_size(current_database()), (SELECT count(*) FROM pg_stat_activity), (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')")
                row = cursor.fetchone()
                if row:
                    database["sizeBytes"], database["connections"], database["maxConnections"] = [int(value) if value is not None else None for value in row]
            elif connection.vendor == "sqlite" and django_settings.DATABASES["default"].get("NAME"):
                try:
                    database["sizeBytes"] = os.path.getsize(django_settings.DATABASES["default"]["NAME"])
                except OSError:
                    pass
        database["status"] = "ok"
    except Exception as exc:
        database["status"] = "error"
        database["error"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"
    database["latencyMs"] = round((time.perf_counter() - start) * 1000, 2)

    redis_metrics = {"status": "unknown", "latencyMs": None, "usedMemoryBytes": None, "connectedClients": None}
    try:
        import redis
        start = time.perf_counter()
        client = redis.Redis.from_url(django_settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        redis_metrics["latencyMs"] = round((time.perf_counter() - start) * 1000, 2)
        redis_metrics["status"] = "ok"
        try:
            info = client.info("memory", "clients")
            redis_metrics["usedMemoryBytes"] = int(info.get("used_memory") or 0) or None
            redis_metrics["connectedClients"] = int(info.get("connected_clients") or 0)
        except Exception:
            pass
    except Exception as exc:
        redis_metrics["status"] = "error"
        redis_metrics["error"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"

    memory_percent = round(memory_used / memory_total * 100, 1) if memory_total else None
    return ok({
        "sampledAt": sampled_at.isoformat(),
        "cpu": {"usagePercent": round(cpu_percent, 1) if cpu_percent is not None else None, "cores": cpu_count, "loadAverage": load_average},
        "memory": {"usedBytes": memory_used, "totalBytes": memory_total, "usagePercent": memory_percent, "processRssBytes": process_rss},
        "disk": {"usedBytes": int(disk.used), "totalBytes": int(disk.total), "freeBytes": int(disk.free), "usagePercent": round(disk.used / disk.total * 100, 1) if disk.total else None},
        "database": database,
        "redis": redis_metrics,
        "runtime": {"uptimeSeconds": system_uptime, "processUptimeSeconds": process_uptime, "python": platform.python_version(), "platform": platform.system()},
    })


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_revenue_chart(request):
    try:
        days = min(90, max(1, int(request.GET.get("days", 30))))
    except ValueError:
        days = 30
    now = timezone.now()
    start = now - timedelta(days=days - 1)
    rows = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        total = SubscriptionPayment.objects.filter(paid_at__date=day).aggregate(total=Sum("amount"))["total"] or 0
        rows.append({"date": day.isoformat(), "amount": float(total)})
    return ok(rows)


@csrf_exempt
@api_view(["GET", "PATCH"])
@admin_required
def admin_subscriptions(request, subscription_id=None):
    if subscription_id:
        subscription = TenantSubscription.objects.select_related("tenant").filter(pk=subscription_id).first()
        if not subscription:
            return err("Subscription not found", 404)
        if method(request, "GET"):
            return ok(subscription_payload(subscription, include_payments=True))
        data = body(request)
        for field in ["plan", "amount", "expires_at", "auto_renew", "notes"]:
            if field in data:
                value = data[field]
                if field == "expires_at":
                    value = parse_date(value)
                setattr(subscription, field, value)
        subscription.save()
        write_audit_log(request.admin["adminId"], request.admin["email"], "UPDATE_SUBSCRIPTION", str(subscription.pk), "subscription", request, tenant_id=subscription.tenant_id)
        return ok({"message": "Subscription updated", "subscription": subscription_payload(subscription)})
    qs = TenantSubscription.objects.select_related("tenant").order_by("expires_at")
    status = request.GET.get("status", "all")
    plan = request.GET.get("plan")
    search = str(request.GET.get("search") or "").lower()
    now = timezone.now()
    if status == "expired":
        qs = qs.filter(expires_at__lt=now)
    elif status == "expiring_soon":
        qs = qs.filter(expires_at__gte=now, expires_at__lte=now + timedelta(days=7))
    elif status == "active":
        qs = qs.filter(expires_at__gte=now)
    if plan and plan != "all":
        qs = qs.filter(plan=plan)
    items = [subscription_payload(item) for item in qs]
    if search:
        items = [item for item in items if search in item.get("tenant_name", "").lower() or search in item.get("tenant_email", "").lower()]
    return ok(paginate_items(request, items))


@csrf_exempt
@api_view(["GET", "POST"])
@admin_required
def admin_subscription_payments(request, subscription_id):
    subscription = TenantSubscription.objects.select_related("tenant").filter(pk=subscription_id).first()
    if not subscription:
        return err("Subscription not found", 404)
    if method(request, "GET"):
        return ok([payment.as_dict() for payment in subscription.payments.order_by("-paid_at")])
    payment = record_subscription_payment(subscription, body(request), request.admin.get("email"))
    write_audit_log(request.admin["adminId"], request.admin["email"], "RECORD_SUBSCRIPTION_PAYMENT", str(subscription.pk), "subscription", request, {"payment_id": payment.pk}, tenant_id=subscription.tenant_id)
    return ok({"message": "Payment recorded", "payment": payment.as_dict(), "subscription": subscription_payload(subscription)})


@csrf_exempt
@api_view(["GET", "PATCH", "POST"])
@admin_required
def admin_tenant_subscription(request, tenant_id):
    tenant = Tenant.objects.filter(pk=tenant_id).first()
    if not tenant:
        return err("Tenant not found", 404)
    subscription = ensure_subscription(tenant)
    if method(request, "GET"):
        return ok(subscription_payload(subscription, include_payments=True))
    if method(request, "PATCH"):
        data = body(request)
        for field in ["plan", "amount", "expires_at", "auto_renew", "notes"]:
            if field in data:
                value = data[field]
                if field == "expires_at":
                    value = parse_date(value)
                setattr(subscription, field, value)
        subscription.save()
        write_audit_log(request.admin["adminId"], request.admin["email"], "UPDATE_TENANT_SUBSCRIPTION", tenant_id, "tenant", request, tenant_id=tenant_id)
        return ok({"message": "Subscription updated", "subscription": subscription_payload(subscription, include_payments=True)})
    payment = record_subscription_payment(subscription, body(request), request.admin.get("email"))
    write_audit_log(request.admin["adminId"], request.admin["email"], "RECORD_TENANT_SUBSCRIPTION_PAYMENT", tenant_id, "tenant", request, {"payment_id": payment.pk}, tenant_id=tenant_id)
    return ok({"message": "Payment recorded", "payment": payment.as_dict(), "subscription": subscription_payload(subscription, include_payments=True)})


@csrf_exempt
@api_view(["POST"])
@admin_required
def admin_subscription_remind(request, tenant_id):
    write_audit_log(request.admin["adminId"], request.admin["email"], "SEND_SUBSCRIPTION_REMINDER", tenant_id, "tenant", request, tenant_id=tenant_id)
    return ok({"message": "Reminder queued"})


@csrf_exempt
@api_view(["POST"])
@admin_required
def admin_mikrotik_test(request, tenant_id):
    tenant = ref(f"tenants/{tenant_id}").get()
    if not tenant:
        return err("Tenant not found", 404)
    try:
        profiles = router_items({"id": tenant_id, **tenant}, "ppp", "profile")
        return ok({"success": True, "error": None, "routers_count": len(profiles), "profile_count": len(profiles)})
    except Exception as exc:
        return ok({"success": False, "error": str(exc), "routers_count": 0}, 400)


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_system_migrations(request):
    out = StringIO()
    call_command("showmigrations", stdout=out)
    return ok({"migrations": out.getvalue().splitlines()})


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_system(request):
    return ok({"health": health_payload(), "database": settings.DATABASES["default"]["ENGINE"], "rate_limits": SimpleRateLimitMiddleware.RULES if False else {}})


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_legacy_stats_unreachable(request):
    tenants = list_children("tenants")
    today = iso_now()[:10]
    total_customers = 0
    payments_today = 0
    for tenant in tenants:
        total_customers += len(list_children(f"tenants/{tenant['id']}/customers"))
        for payment in list_children(f"tenants/{tenant['id']}/payments"):
            if payment.get("paid_at") and str(payment["paid_at"])[:10] == today:
                payments_today += float(payment.get("amount") or 0)
    return ok({"totalTenants": len(tenants), "activeTenants": len([t for t in tenants if t.get("status") != "suspended"]), "suspendedTenants": len([t for t in tenants if t.get("status") == "suspended"]), "totalCustomers": total_customers, "paymentsToday": payments_today, "systemHealth": "healthy"})


@csrf_exempt
@api_view(["GET"])
@admin_required
def admin_audit_logs(request):
    records = AdminAuditLog.objects.all()
    now = timezone.now()
    summary = records.aggregate(
        total=Count("id"),
        today=Count("id", filter=Q(timestamp__date=now.date())),
        recent=Count("id", filter=Q(timestamp__gte=now - timedelta(days=7))),
        updates=Count("id", filter=Q(action__icontains="UPDATE") | Q(action__icontains="PATCH")),
        deletions=Count("id", filter=Q(action__icontains="DELETE")),
    )
    page_size = 15
    try:
        page_number = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page_number = 1
    offset = (page_number - 1) * page_size
    ordered_records = records.order_by("-timestamp", "-id")
    rows = list(ordered_records[offset:offset + page_size + 1])
    has_more = len(rows) > page_size
    logs = [item.as_dict() for item in rows[:page_size]]
    return ok({"results": logs, "summary": summary, "pageSize": page_size, "page": page_number, "hasMore": has_more})


@csrf_exempt
@api_view(["GET", "PATCH"])
@admin_required
def admin_site(request):
    if method(request, "GET"):
        return ok({**(ref("site_settings").get() or {}), "system_subscription_fee_percent": float(system_subscription_fee_percent())})
    data = body(request)
    allowed = ["brand_name", "headline", "subheadline", "about", "phone", "email", "location", "address", "cta_label", "cta_url", "subscription_bank_name", "subscription_bank_account_name", "subscription_bank_account_number", "subscription_bank_branch", "subscription_payment_instructions"]
    updates = {field: data[field] for field in allowed if field in data}
    ref("site_settings").update({**updates, "updated_at": iso_now(), "updated_by": request.admin["adminId"]})
    write_audit_log(request.admin["adminId"], request.admin["email"], "UPDATE_SITE", target_type="site", request=request, metadata={"updated_fields": list(updates)})
    return ok({"message": "Site settings updated"})


PLATFORM_NOTIFICATION_TYPES = [
    {
        "key": "whatsapp_on_customer_created",
        "name": "Customer created",
        "description": "Sent when a PPPoE or Static customer account is created. Includes the assigned package and payable amount.",
        "message": "Welcome to [ISP_NAME]! Your internet account has been successfully created.\n\nPackage: [PACKAGE_NAME]\nAmount Payable: KSh [PACKAGE_AMOUNT]\n\nPlease make payment to activate your internet service.\n\nThank you for choosing [ISP_NAME].",
    },
    {
        "key": "sms_on_payment",
        "name": "Package payments",
        "description": "Sent after a customer successfully pays for their assigned internet package and the payment is confirmed.",
        "message": "Payment received! We have successfully received your payment of KSh [AMOUNT_PAID] for the [PACKAGE_NAME] package.\n\nYour payment has been confirmed and your internet service is being activated.\n\nThank you for choosing [ISP_NAME].",
    },
    {
        "key": "whatsapp_on_expiry",
        "name": "Package expiry",
        "description": "Sent before a customer's package expires.",
        "message": "[ISP_NAME] Reminder: Your [PACKAGE_NAME] package will expire on [EXPIRY_DATE].\n\nPlease renew your package before the expiry date to avoid interruption of your internet service.\n\nThank you for choosing [ISP_NAME].",
    },
    {
        "key": "sms_on_maintenance",
        "name": "Maintenance notices",
        "description": "Used to notify customers about planned service maintenance.",
        "message": "[ISP_NAME] Maintenance Notice:\n\nWe will be performing planned maintenance on [MAINTENANCE_DATE] from [START_TIME] to [END_TIME].\n\nCustomers in [AFFECTED_AREA] may experience temporary interruptions during this period.\n\nWe apologize for any inconvenience and appreciate your understanding.\n\nFor assistance, contact [SUPPORT_CONTACT].",
    },
    {
        "key": "sms_on_promotions",
        "name": "Promotions",
        "description": "Used for offers, discounts, new packages, and customer promotional announcements.",
        "message": "[ISP_NAME] Offer:\n\n[PROMOTION_MESSAGE]\n\nOffer valid until [PROMOTION_EXPIRY_DATE].\n\nFor more information, contact [SUPPORT_CONTACT].",
    },
]


def _platform_settings():
    data = dict(ref("site_settings").get() or {})
    return data


@csrf_exempt
@api_view(["GET", "PATCH"])
@admin_required
def admin_communications(request):
    settings_data = _platform_settings()
    if method(request, "GET"):
        toggles = {
            item["key"]: settings_data.get(item["key"]) is not False
            for item in PLATFORM_NOTIFICATION_TYPES
        }
        return ok({
            "notification_types": [
                {**item, "enabled": toggles[item["key"]]}
                for item in PLATFORM_NOTIFICATION_TYPES
            ],
            "whatsapp_enabled": settings_data.get("whatsapp_enabled") is not False,
            "sms_enabled": settings_data.get("sms_enabled") is not False,
        })

    data = body(request)
    allowed = {item["key"] for item in PLATFORM_NOTIFICATION_TYPES} | {"whatsapp_enabled", "sms_enabled"}
    updates = {field: data[field] is not False for field in allowed if field in data}
    updates.update({"communications_updated_at": iso_now(), "updated_by": request.admin["adminId"]})
    ref("site_settings").update(updates)
    write_audit_log(request.admin["adminId"], request.admin["email"], "UPDATE_COMMUNICATIONS", target_type="site", request=request, metadata={"updated_fields": list(updates)})
    return ok({"success": True, "message": "Communication settings saved", "config": updates})


@csrf_exempt
@api_view(["GET", "PATCH", "POST"])
@admin_required
def admin_integrations(request):
    settings_data = _platform_settings()
    if method(request, "GET"):
        apiwap_configured = bool(
            settings_data.get("apiwap_api_key")
            or os.getenv("APIWAP_TOKEN")
            or os.getenv("APIWAP_API_KEY")
        )
        slek_configured = bool(os.getenv("SLEK_KEY") and os.getenv("SLEK_SECRET"))
        return ok({
            "notification_provider": settings_data.get("notification_provider") or os.getenv("WHATSAPP_PROVIDER") or "slek",
            "collection_provider": "daraja",
            "whatsapp_enabled": settings_data.get("whatsapp_enabled") is not False,
            "apiwap_configured": apiwap_configured,
            "slek_configured": slek_configured,
        })

    data = body(request)
    if method(request, "POST"):
        provider = str(data.get("provider") or settings_data.get("notification_provider") or "apiwap").strip()
        tenant_like = {
            "business_name": settings_data.get("brand_name") or "Expressnet",
            "notification_provider": provider,
            "whatsapp_enabled": True,
            "apiwap_base_url": data.get("apiwap_base_url") or settings_data.get("apiwap_base_url"),
            "apiwap_api_key": data.get("apiwap_api_key") if data.get("apiwap_api_key") not in {MASKED, "********"} else settings_data.get("apiwap_api_key"),
        }
        phone = normalize_phone(data.get("phone") or settings_data.get("phone"))
        if not phone:
            return ok({"message": "Phone number is required to test the integration"}, 400)
        result = send_whatsapp_message(phone, data.get("message") or "ApiWap test notification from Expressnet admin.", tenant_like)
        if result.get("sent"):
            return ok({"success": True, "message": "Integration test sent", "result": result})
        return ok({"success": False, "message": result.get("error") or result.get("skipped") or "Integration test failed", "result": result}, 400)

    updates = {
        "notification_provider": str(data.get("notification_provider") or data.get("provider") or settings_data.get("notification_provider") or os.getenv("WHATSAPP_PROVIDER") or "slek").strip().lower(),
        "collection_provider": "daraja",
        "whatsapp_enabled": data.get("whatsapp_enabled", settings_data.get("whatsapp_enabled", True)) is not False,
        "apiwap_base_url": str(data.get("apiwap_base_url") or settings_data.get("apiwap_base_url") or "https://api.apiwap.com/api/v1").strip(),
        "integrations_updated_at": iso_now(),
        "updated_by": request.admin["adminId"],
    }
    if updates["notification_provider"] not in {"apiwap", "slek"}:
        return ok({"message": "Notification provider must be ApiWap or Slek"}, 400)
    apiwap_api_key = str(data.get("apiwap_api_key") or "").strip()
    if apiwap_api_key and apiwap_api_key not in {MASKED, "********", "••••••••"}:
        updates["apiwap_api_key"] = apiwap_api_key
    ref("site_settings").update(updates)
    write_audit_log(request.admin["adminId"], request.admin["email"], "UPDATE_INTEGRATIONS", target_type="site", request=request, metadata={"updated_fields": [key for key in updates if key != "apiwap_api_key"]})
    saved = {**settings_data, **updates}
    return ok({
        "success": True,
        "message": "Integration settings saved",
        "notification_provider": saved.get("notification_provider") or "slek",
        "whatsapp_enabled": saved.get("whatsapp_enabled") is not False,
        "apiwap_configured": bool(saved.get("apiwap_api_key") or os.getenv("APIWAP_TOKEN") or os.getenv("APIWAP_API_KEY")),
        "slek_configured": bool(os.getenv("SLEK_KEY") and os.getenv("SLEK_SECRET")),
        "collection_provider": saved.get("collection_provider") or "daraja",
    })


@csrf_exempt
@api_view(["GET", "PATCH", "POST"])
@admin_required
def admin_users(request, tenant_id=None, customer_id=None, action=None):
    if method(request, "GET"):
        users = []
        for tenant in list_children("tenants"):
            for customer in list_children(f"tenants/{tenant['id']}/customers"):
                users.append({**customer, "tenant_id": tenant["id"], "tenant_name": tenant.get("business_name")})
        return ok(users)
    tenant = {"id": tenant_id, **(ref(f"tenants/{tenant_id}").get() or {})}
    customer = ref(f"tenants/{tenant_id}/customers/{customer_id}").get()
    if not tenant or not customer:
        return ok({"error": "Tenant or user not found"}, 404)
    if method(request, "PATCH"):
        data = body(request)
        allowed = ["name", "phone", "username", "package", "status", "expiry_date", "auto_reconnect"]
        updates = {field: data[field] for field in allowed if field in data}
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update(updates)
        write_audit_log(request.admin["adminId"], request.admin["email"], "UPDATE_USER", customer_id, "customer", request, {"tenantId": tenant_id, "updated_fields": list(updates)}, tenant_id=tenant_id)
        return ok({"message": "User updated"})
    if action == "reconnect":
        set_customer_enabled(tenant, customer.get("username"), customer.get("service_type", "hotspot"), True)
        write_audit_log(request.admin["adminId"], request.admin["email"], "RECONNECT_USER", customer_id, "customer", request, {"tenantId": tenant_id}, tenant_id=tenant_id)
        return ok({"message": "User reconnected"})
    if action == "disable":
        set_customer_enabled(tenant, customer.get("username"), customer.get("service_type", "hotspot"), False)
        ref(f"tenants/{tenant_id}/customers/{customer_id}").update({"status": "inactive"})
        write_audit_log(request.admin["adminId"], request.admin["email"], "DISABLE_USER", customer_id, "customer", request, {"tenantId": tenant_id}, tenant_id=tenant_id)
        return ok({"message": "User disabled"})
    return ok({"message": "Method not allowed"}, 405)
