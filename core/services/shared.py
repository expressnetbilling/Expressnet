import base64
import hashlib
import hmac
import os
import socket
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlparse, urlsplit, urlunsplit

import bcrypt
import jwt
import requests
from django.conf import settings

from billing_api.models import AdminAuditLog, AdminUser, Customer, InternetPackage, Payment, SiteSettings, Tenant, Ticket, Voucher


class PaymentProviderError(RuntimeError):
    def __init__(self, public_message, detail=None, status_code=502):
        super().__init__(detail or public_message)
        self.public_message = public_message
        self.detail = detail or public_message
        self.status_code = status_code


def utcnow():
    return datetime.now(timezone.utc)


def iso_now():
    return utcnow().isoformat().replace("+00:00", "Z")


def require_secret(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    if len(value) < 16:
        raise RuntimeError(f"{name} must be at least 16 characters")
    return value


def model_dict(instance, include_id=True, exclude=None):
    return instance.as_dict(include_id=include_id, exclude=exclude) if hasattr(instance, "as_dict") else {}


def model_update(instance, data):
    instance.apply_data(data)
    instance.save()
    return instance


class OrmRef:
    def __init__(self, path=""):
        self.parts = [part for part in str(path).strip("/").split("/") if part]
        self.key = None

    def _tenant(self, tenant_id):
        return Tenant.objects.get(pk=tenant_id)

    def _package(self, tenant_id, package_id):
        return InternetPackage.objects.get(tenant_id=tenant_id, pk=package_id)

    def _customer(self, tenant_id, customer_id):
        return Customer.objects.get(tenant_id=tenant_id, pk=customer_id)

    def _payment(self, tenant_id, payment_id):
        return Payment.objects.get(tenant_id=tenant_id, pk=payment_id)

    def _ticket(self, tenant_id, ticket_id):
        return Ticket.objects.get(tenant_id=tenant_id, pk=ticket_id)

    def _site_settings(self):
        return SiteSettings.objects.order_by("pk").first()

    def _resolve_instance(self):
        parts = self.parts
        if len(parts) == 2 and parts[0] == "tenants":
            return self._tenant(parts[1])
        if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "packages":
            return self._package(parts[1], parts[3])
        if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "customers":
            return self._customer(parts[1], parts[3])
        if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "payments":
            return self._payment(parts[1], parts[3])
        if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "tickets":
            return self._ticket(parts[1], parts[3])
        if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "vouchers":
            return Voucher.objects.get(tenant_id=parts[1], pk=parts[3])
        if len(parts) == 2 and parts[0] == "admins":
            return AdminUser.objects.get(pk=parts[1])
        if parts == ["site_settings"]:
            return self._site_settings()
        raise KeyError(f"Unsupported relational ref path: {'/'.join(parts)}")

    def get(self):
        parts = self.parts
        try:
            if parts == ["tenants"]:
                return {str(item.pk): model_dict(item, include_id=False) for item in Tenant.objects.all()}
            if len(parts) == 2 and parts[0] == "tenants":
                return model_dict(self._tenant(parts[1]), include_id=False)
            if len(parts) == 3 and parts[0] == "tenants" and parts[2] == "packages":
                return {str(item.pk): model_dict(item, include_id=False) for item in InternetPackage.objects.filter(tenant_id=parts[1])}
            if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "packages":
                return model_dict(self._package(parts[1], parts[3]), include_id=False)
            if len(parts) == 3 and parts[0] == "tenants" and parts[2] == "customers":
                return {str(item.pk): model_dict(item, include_id=False, exclude={"password"}) for item in Customer.objects.filter(tenant_id=parts[1])}
            if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "customers":
                return model_dict(self._customer(parts[1], parts[3]), include_id=False)
            if len(parts) == 3 and parts[0] == "tenants" and parts[2] == "payments":
                return {str(item.pk): model_dict(item, include_id=False) for item in Payment.objects.filter(tenant_id=parts[1])}
            if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "payments":
                return model_dict(self._payment(parts[1], parts[3]), include_id=False)
            if len(parts) == 3 and parts[0] == "tenants" and parts[2] == "tickets":
                return {str(item.pk): model_dict(item, include_id=False) for item in Ticket.objects.filter(tenant_id=parts[1])}
            if len(parts) == 3 and parts[0] == "tenants" and parts[2] == "vouchers":
                return {str(item.pk): model_dict(item, include_id=False) for item in Voucher.objects.filter(tenant_id=parts[1])}
            if len(parts) == 4 and parts[0] == "tenants" and parts[2] == "tickets":
                return model_dict(self._ticket(parts[1], parts[3]), include_id=False)
            if parts == ["admins"]:
                return {str(item.pk): model_dict(item, include_id=False) for item in AdminUser.objects.all()}
            if len(parts) == 2 and parts[0] == "admins":
                return model_dict(AdminUser.objects.get(pk=parts[1]), include_id=False)
            if parts == ["site_settings"]:
                settings = self._site_settings()
                return model_dict(settings, include_id=False) if settings else {}
            if parts == ["admin_audit_logs"]:
                return {str(item.pk): item.as_dict(include_id=False) for item in AdminAuditLog.objects.all()}
        except (Tenant.DoesNotExist, InternetPackage.DoesNotExist, Customer.DoesNotExist, Payment.DoesNotExist, Ticket.DoesNotExist, Voucher.DoesNotExist, AdminUser.DoesNotExist):
            return None
        raise KeyError(f"Unsupported relational ref path: {'/'.join(parts)}")

    def push(self, data):
        parts = self.parts
        if parts == ["tenants"]:
            instance = Tenant()
        elif len(parts) == 3 and parts[0] == "tenants" and parts[2] == "packages":
            instance = InternetPackage(tenant_id=parts[1])
        elif len(parts) == 3 and parts[0] == "tenants" and parts[2] == "customers":
            instance = Customer(tenant_id=parts[1])
        elif len(parts) == 3 and parts[0] == "tenants" and parts[2] == "payments":
            instance = Payment(tenant_id=parts[1])
        elif len(parts) == 3 and parts[0] == "tenants" and parts[2] == "tickets":
            instance = Ticket(tenant_id=parts[1])
        elif len(parts) == 3 and parts[0] == "tenants" and parts[2] == "vouchers":
            instance = Voucher(tenant_id=parts[1])
        elif parts == ["admins"]:
            instance = AdminUser()
        elif parts == ["admin_audit_logs"]:
            instance = AdminAuditLog()
        else:
            raise KeyError(f"Unsupported relational push path: {'/'.join(parts)}")

        if hasattr(instance, "apply_data"):
            instance.apply_data(dict(data or {}))
        else:
            for key, value in (data or {}).items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
        instance.save()
        return OrmPushResult(instance)

    def update(self, data):
        parts = self.parts
        if parts == ["site_settings"]:
            instance = self._site_settings() or SiteSettings()
            model_update(instance, dict(data or {}))
            return
        instance = self._resolve_instance()
        if not instance:
            return
        model_update(instance, dict(data or {}))

    def delete(self):
        instance = self._resolve_instance()
        if instance:
            instance.delete()


class OrmPushResult:
    def __init__(self, instance):
        self.instance = instance
        self.key = str(instance.pk)

    def get(self):
        return model_dict(self.instance, include_id=False)

    def update(self, data):
        model_update(self.instance, dict(data or {}))


def ref(path=""):
    return OrmRef(path)


def list_children(path):
    value = ref(path).get() or {}
    if not isinstance(value, dict):
        return []
    return [{"id": key, **(item or {})} for key, item in value.items()]


def find_child_by_field(path, field, expected):
    expected = str(expected).lower().strip()
    for item in list_children(path):
        if str(item.get(field, "")).lower().strip() == expected:
            return item
    return None


def hash_password(password):
    return bcrypt.hashpw(str(password).encode(), bcrypt.gensalt(rounds=10)).decode()


def check_password(password, hashed):
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(str(password).encode(), str(hashed).encode())
    except (ValueError, TypeError):
        return False


def make_payment_access_token(tenant_id, payment_id):
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        f"payment-access:{tenant_id}:{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


def verify_payment_access_token(tenant_id, payment_id, token):
    return hmac.compare_digest(make_payment_access_token(tenant_id, payment_id), str(token or ""))


def _get_jwt_secret(name):
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} is not configured. Please set it in your .env file.")
    return value


def tenant_token(tenant_id, member_id=None):
    payload = {"id": tenant_id, "exp": utcnow() + timedelta(days=7)}
    if member_id:
        payload["member_id"] = member_id
    return jwt.encode(
        payload,
        _get_jwt_secret("JWT_SECRET"),
        algorithm="HS256",
    )


def admin_token(admin_id, admin_data):
    return jwt.encode(
        {
            "adminId": admin_id,
            "email": admin_data.get("email"),
            "name": admin_data.get("name"),
            "role": "admin",
            "exp": utcnow() + timedelta(hours=4),
        },
        _get_jwt_secret("ADMIN_JWT_SECRET"),
        algorithm="HS256",
    )


def decode_tenant_token(token):
    return jwt.decode(token, _get_jwt_secret("JWT_SECRET"), algorithms=["HS256"])


def decode_admin_token(token):
    return jwt.decode(token, _get_jwt_secret("ADMIN_JWT_SECRET"), algorithms=["HS256"])


def normalize_phone(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("254") and len(digits) == 12:
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return f"254{digits[1:]}"
    if digits.startswith(("7", "1")) and len(digits) == 9:
        return f"254{digits}"
    return digits


def selected_collection_provider(tenant=None, requested_provider=None, platform_default=None):
    # Paystack checkout is paused. Treat stale tenant/platform settings and
    # client-supplied provider values as Daraja until another provider is enabled.
    return "daraja"


def normalize_public_url(value):
    value = str(value or "").strip().strip("\"'").rstrip("/")
    while value.startswith("http://https://"):
        value = "https://" + value[len("http://https://") :]
    while value.startswith("https://http://"):
        value = "http://" + value[len("https://http://") :]
    if value.startswith("//"):
        value = "https:" + value
    if value and not value.startswith(("http://", "https://")):
        value = "https://" + value
    parts = urlsplit(value)
    if parts.path.rstrip("/") == "/api":
        value = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    return value.rstrip("/")


def get_public_base_url():
    candidates = [
        os.getenv("DARAJA_CALLBACK_BASE_URL"),
        getattr(settings, "DARAJA_CALLBACK_BASE_URL", ""),
        os.getenv("PUBLIC_APP_URL"),
        getattr(settings, "PUBLIC_APP_URL", ""),
    ]
    if not settings.DEBUG:
        candidates = [item for item in candidates if item and "localhost" not in item and "127.0.0.1" not in item]
    configured = next((item for item in candidates if item), "")
    return normalize_public_url(configured)




def write_audit_log(admin_id=None, admin_email=None, action=None, target_id=None, target_type=None, request=None, metadata=None, actor_type="admin", tenant_id=None):
    ref("admin_audit_logs").push(
        {
            "admin_id": admin_id,
            "admin_email": admin_email,
            "actor_type": actor_type,
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
            "action": action,
            "target_id": target_id,
            "target_type": target_type,
            "ip": request.META.get("REMOTE_ADDR") if request else None,
            "user_agent": request.META.get("HTTP_USER_AGENT") if request else None,
            "metadata": metadata or {},
        }
    )
