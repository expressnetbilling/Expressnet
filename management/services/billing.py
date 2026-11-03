import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import re
import socket
import ssl
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qsl, urlparse, urlsplit, urlunsplit

import bcrypt
import jwt
import requests
from django.conf import settings

from billing_api.models import AdminAuditLog, AdminUser, Customer, InternetPackage, Payment, SiteSettings, Tenant, Ticket, Voucher


logger = logging.getLogger(__name__)



from core.services.shared import *


PAYSTACK_API_BASE = "https://api.paystack.co"


def paystack_secret_key():
    configured = os.getenv("PAYSTACK_SECRET_KEY") or getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if configured:
        return str(configured).strip()
    try:
        platform_settings = ref("site_settings").get() or {}
    except Exception:
        platform_settings = {}
    return str(platform_settings.get("paystack_secret_key") or "").strip()


def tenant_paystack_platform_fee_percent():
    try:
        return max(0.0, min(100.0, float(os.getenv("PAYSTACK_PLATFORM_FEE_PERCENT", "0") or 0)))
    except (TypeError, ValueError):
        return 0.0


def initiate_paystack_checkout(*, email, amount, reference, callback_url, currency="KES", subaccount=None, bearer="account", metadata=None):
    secret = paystack_secret_key()
    if not secret:
        raise PaymentProviderError("Paystack checkout is not configured yet. Please contact support.", "Missing PAYSTACK_SECRET_KEY", 503)
    minor_units = int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    payload = {"email": email, "amount": str(minor_units), "currency": currency or "KES", "reference": reference, "callback_url": callback_url, "metadata": metadata or {}}
    if subaccount:
        payload["subaccount"] = subaccount
        payload["bearer"] = "subaccount" if bearer == "subaccount" else "account"
        charge_percent = tenant_paystack_platform_fee_percent()
        if charge_percent:
            payload["transaction_charge"] = int((Decimal(str(amount)) * Decimal("100") * Decimal(str(charge_percent)) / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    response = requests.post(f"{PAYSTACK_API_BASE}/transaction/initialize", headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("status") is not True or not result.get("data", {}).get("authorization_url"):
        raise PaymentProviderError(result.get("message") or "Paystack did not return a checkout URL", json.dumps(result), 502)
    return result["data"]


def initiate_paystack_mpesa_stk(*, email, amount, phone, reference, currency="KES", subaccount=None, bearer="account", metadata=None):
    """Start a Paystack M-Pesa mobile money charge (customer authorizes by STK PIN)."""
    secret = paystack_secret_key()
    if not secret:
        raise PaymentProviderError("Paystack M-Pesa payments are not configured yet. Please contact support.", "Missing PAYSTACK_SECRET_KEY", 503)
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    if not digits.startswith("254"):
        digits = "254" + digits
    mobile = f"+{digits}"
    minor_units = int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    payload = {
        "email": email,
        "amount": str(minor_units),
        "currency": currency or "KES",
        "reference": reference,
        "mobile_money": {"phone": mobile, "provider": "mpesa"},
        "metadata": metadata or {},
    }
    if subaccount:
        payload["subaccount"] = subaccount
        payload["bearer"] = "subaccount" if bearer == "subaccount" else "account"
        charge_percent = tenant_paystack_platform_fee_percent()
        if charge_percent:
            payload["transaction_charge"] = int((Decimal(str(amount)) * Decimal("100") * Decimal(str(charge_percent)) / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    try:
        response = requests.post(f"{PAYSTACK_API_BASE}/charge", headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, json=payload, timeout=30)
    except requests.RequestException as exc:
        raise PaymentProviderError(
            "We could not confirm the payment prompt response yet. Do not start another payment; this page will check the transaction status.",
            f"Paystack charge outcome is uncertain: {type(exc).__name__}",
            202,
        ) from exc
    if response.status_code >= 500:
        raise PaymentProviderError(
            "We could not confirm the payment prompt response yet. Do not start another payment; this page will check the transaction status.",
            f"Paystack charge returned HTTP {response.status_code}; outcome is uncertain",
            202,
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            error_payload = response.json()
        except (ValueError, json.JSONDecodeError):
            error_payload = {}
        message = str(error_payload.get("message") or "Paystack could not start the M-Pesa prompt")
        raise PaymentProviderError(message, f"Paystack charge HTTP {response.status_code}", response.status_code if 400 <= response.status_code < 500 else 502) from exc
    result = response.json()
    charge = result.get("data") or {}
    if result.get("status") is not True or not charge.get("reference"):
        raise PaymentProviderError(result.get("message") or "Paystack could not start the M-Pesa prompt", json.dumps(result), 502)
    return charge


def create_paystack_subaccount(*, tenant, percentage_charge=0):
    """Create a Paystack subaccount linked to the tenant's configured bank."""
    secret = paystack_secret_key()
    if not secret:
        raise PaymentProviderError("Paystack is not configured yet. Please contact support.", "Missing Paystack secret key", 503)
    bank_code = str(tenant.get("bank_code") or "").strip()
    account_number = str(tenant.get("bank_account_number") or "").strip()
    if not bank_code or not account_number:
        raise PaymentProviderError("Add the tenant bank code and account number before enabling Paystack settlement.", "Missing tenant bank details", 400)
    payload = {
        "business_name": str(tenant.get("business_name") or tenant.get("email") or "Tenant").strip(),
        "bank_code": bank_code,
        "account_number": account_number,
        "percentage_charge": float(percentage_charge),
        # Ensure the tenant share is paid out to its configured bank account
        # automatically instead of remaining in a manually settled balance.
        "settlement_schedule": "auto",
        "metadata": {"tenant_id": str(tenant.get("id") or "")},
    }
    try:
        response = requests.post(
            f"{PAYSTACK_API_BASE}/subaccount",
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise PaymentProviderError(
            "Could not connect to Paystack while setting up this bank account. Check the server connection and try again.",
            f"Paystack subaccount request failed: {type(exc).__name__}",
            502,
        ) from exc
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            result = response.json()
        except (ValueError, json.JSONDecodeError):
            result = {}
        message = str(result.get("message") or "Paystack rejected this bank account setup.").strip()
        logger.warning(
            "Paystack rejected subaccount setup: status=%s bank_code=%s message=%s",
            response.status_code,
            bank_code,
            message,
        )
        # Keep Paystack's actionable validation message, but never expose request credentials.
        raise PaymentProviderError(message, f"Paystack subaccount HTTP {response.status_code}", response.status_code if 400 <= response.status_code < 500 else 502) from exc
    try:
        result = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise PaymentProviderError(
            "Paystack returned an unreadable response while setting up this bank account. Try again shortly.",
            f"Paystack subaccount returned invalid JSON: {type(exc).__name__}",
            502,
        ) from exc
    code = (result.get("data") or {}).get("subaccount_code")
    if result.get("status") is not True or not code:
        raise PaymentProviderError(result.get("message") or "Paystack did not create a settlement subaccount.", json.dumps(result), 502)
    return result["data"]


def fetch_paystack_subaccount(subaccount_code):
    """Return an existing subaccount, or None when Paystack no longer has it."""
    secret = paystack_secret_key()
    if not secret:
        raise PaymentProviderError("Paystack is not configured yet. Please contact support.", "Missing Paystack secret key", 503)
    response = requests.get(
        f"{PAYSTACK_API_BASE}/subaccount/{subaccount_code}",
        headers={"Authorization": f"Bearer {secret}"},
        timeout=20,
    )
    if response.status_code == 404:
        return None
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            result = response.json()
        except (ValueError, json.JSONDecodeError):
            result = {}
        raise PaymentProviderError(
            "Could not verify this tenant's Paystack subaccount. Try again shortly.",
            str(result.get("message") or f"Paystack subaccount lookup HTTP {response.status_code}"),
            response.status_code if 400 <= response.status_code < 500 else 502,
        ) from exc
    try:
        result = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise PaymentProviderError(
            "Paystack returned an unreadable response while checking the tenant subaccount.",
            f"Paystack subaccount lookup returned invalid JSON: {type(exc).__name__}",
            502,
        ) from exc
    if result.get("status") is not True:
        # A successful HTTP response with no subaccount data is treated as stale.
        if "not found" in str(result.get("message") or "").casefold():
            return None
        raise PaymentProviderError(
            "Could not verify this tenant's Paystack subaccount. Try again shortly.",
            str(result.get("message") or "Paystack subaccount lookup failed"),
            502,
        )
    return result.get("data") or None


def list_paystack_banks(country="kenya"):
    """Return active Kenyan bank transfer recipients and codes from Paystack."""
    secret = paystack_secret_key()
    if not secret:
        raise PaymentProviderError("Bank list is not available right now. Please contact support.", "Missing PAYSTACK_SECRET_KEY", 503)
    response = requests.get(
        f"{PAYSTACK_API_BASE}/bank",
        headers={"Authorization": f"Bearer {secret}"},
        params={"currency": "KES", "type": "kepss", "perPage": 100},
        timeout=20,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise PaymentProviderError("Could not load the bank list from Paystack. Try again shortly.", f"Paystack bank list HTTP {response.status_code}", response.status_code if 400 <= response.status_code < 500 else 502) from exc
    result = response.json()
    if result.get("status") is not True:
        raise PaymentProviderError("Could not load the bank list from Paystack. Try again shortly.", str(result.get("message") or "Bank list unavailable"), 502)
    banks = [
        {"name": str(bank.get("name") or "").strip(), "code": str(bank.get("code") or "").strip()}
        for bank in result.get("data") or []
        if bank.get("active") and not bank.get("is_deleted") and bank.get("name") and bank.get("code")
    ]
    return sorted(banks, key=lambda bank: bank["name"].casefold())


def _paystack_transfer_request(method, path, *, payload=None, params=None):
    secret = paystack_secret_key()
    if not secret:
        raise PaymentProviderError("Paystack withdrawals are not configured. Please contact support.", "Missing PAYSTACK_SECRET_KEY", 503)
    try:
        response = requests.request(
            method,
            f"{PAYSTACK_API_BASE}{path}",
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            json=payload,
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise PaymentProviderError(
            "Paystack could not be reached. Check the withdrawal status before trying again.",
            f"Paystack transfer request failed: {type(exc).__name__}",
            502,
        ) from exc
    try:
        result = response.json()
    except (ValueError, json.JSONDecodeError):
        result = {}
    if response.status_code >= 400 or result.get("status") is not True:
        message = str(result.get("message") or "Paystack rejected the withdrawal request.")
        raise PaymentProviderError(message, f"Paystack {method} {path} HTTP {response.status_code}", response.status_code if 400 <= response.status_code < 500 else 502)
    return result.get("data") or {}


def create_paystack_transfer_recipient(*, payout_method, name, email, currency="KES", bank_code="", account_number=""):
    if payout_method == "mpesa":
        payload = {
            "type": "mobile_money",
            "name": name,
            "email": email,
            "account_number": account_number,
            "bank_code": "MPESA",
            "currency": currency,
        }
    else:
        payload = {
            "type": "kepss",
            "name": name,
            "email": email,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        }
    return _paystack_transfer_request("POST", "/transferrecipient", payload=payload)


def get_paystack_balance(currency="KES"):
    balances = _paystack_transfer_request("GET", "/balance", params={"currency": currency})
    if isinstance(balances, dict):
        balances = [balances]
    for item in balances if isinstance(balances, list) else []:
        if str(item.get("currency") or "").upper() == currency.upper():
            return int(item.get("balance") or 0)
    return 0


def initiate_paystack_transfer(*, amount, recipient_code, reference, reason, currency="KES"):
    minor_units = int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return _paystack_transfer_request(
        "POST",
        "/transfer",
        payload={"source": "balance", "amount": minor_units, "recipient": recipient_code, "reference": reference, "reason": reason, "currency": currency},
    )


def finalize_paystack_transfer(*, transfer_code, otp):
    return _paystack_transfer_request(
        "POST",
        "/transfer/finalize_transfer",
        payload={"transfer_code": transfer_code, "otp": otp},
    )


def verify_paystack_transfer(reference):
    return _paystack_transfer_request("GET", f"/transfer/verify/{reference}")


def verify_paystack_transaction(reference):
    secret = paystack_secret_key()
    if not secret:
        raise PaymentProviderError("Paystack verification is not configured.", "Missing PAYSTACK_SECRET_KEY", 503)
    response = requests.get(f"{PAYSTACK_API_BASE}/transaction/verify/{reference}", headers={"Authorization": f"Bearer {secret}"}, timeout=30)
    response.raise_for_status()
    result = response.json()
    if result.get("status") is not True:
        raise PaymentProviderError(result.get("message") or "Paystack verification failed", json.dumps(result), 502)
    return result.get("data") or {}


def paystack_signature_valid(raw_body, signature):
    secret = paystack_secret_key()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, str(signature))

def initiate_daraja_stk(tenant, payment_id, amount, phone, payment_method="daraja_paybill", description=None):
    """Start a Daraja STK push for a tenant Paybill or Buy Goods account."""
    consumer_key = str(tenant.get("daraja_consumer_key") or "").strip()
    consumer_secret = str(tenant.get("daraja_consumer_secret") or "").strip()
    passkey = str(tenant.get("daraja_passkey") or "").strip()
    shortcode = str(tenant.get("daraja_shortcode") or "").strip()
    till = str(tenant.get("daraja_till_number") or "").strip()
    if not all([consumer_key, consumer_secret, passkey, shortcode]):
        raise PaymentProviderError("Daraja credentials are incomplete. Add all required M-Pesa API credentials.", "Missing Daraja credentials", 400)
    if payment_method == "daraja_buygoods":
        shortcode = till or shortcode
        transaction_type = "CustomerBuyGoodsOnline"
    else:
        transaction_type = "CustomerPayBillOnline"
    if not shortcode:
        raise PaymentProviderError("The Daraja shortcode or Buy Goods till number is required.", "Missing Daraja shortcode", 400)
    base = daraja_base_url(tenant)
    token_response = requests.get(f"{base}/oauth/v1/generate?grant_type=client_credentials", auth=(consumer_key, consumer_secret), timeout=30)
    token_response.raise_for_status()
    token = token_response.json().get("access_token")
    if not token:
        raise PaymentProviderError("Daraja did not return an access token.", "Missing Daraja access token", 502)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()
    tenant_id = tenant.get("id")
    callback_token = make_daraja_callback_token(tenant_id, payment_id)
    base_url = get_public_base_url()
    if not base_url:
        raise RuntimeError("PUBLIC_APP_URL or DARAJA_CALLBACK_BASE_URL is required for the Daraja callback URL")
    callback_url = f"{base_url}/api/daraja/callback/{tenant_id}/{payment_id}/{callback_token}"
    payload = {"BusinessShortCode": shortcode, "Password": password, "Timestamp": timestamp, "TransactionType": transaction_type, "Amount": max(1, int(round(float(amount or 0)))), "PartyA": normalize_phone(phone), "PartyB": shortcode, "PhoneNumber": normalize_phone(phone), "CallBackURL": callback_url, "AccountReference": str(payment_id), "TransactionDesc": description or "Internet package"}
    response = requests.post(f"{base}/mpesa/stkpush/v1/processrequest", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    if str(result.get("ResponseCode")) != "0":
        raise PaymentProviderError(result.get("ResponseDescription") or "Daraja rejected the payment request.", json.dumps(result), 502)
    return result



# ---------------------------------------------------------------------------
# Daraja (Safaricom M-Pesa) — for tenants who have applied for / been
# approved for their own Daraja API access, rather than the shared
# RoamTech-based SMS/notification path used elsewhere.
#
# A tenant is considered "Daraja-enabled" once they have all four
# credentials configured (consumer key/secret, shortcode, passkey) AND have
# explicitly selected mpesa as their payment_provider. There is no separate
# approval queue in this codebase yet.
# ---------------------------------------------------------------------------

def _clean_daraja_config(source):
    source = source or {}
    return {
        "daraja_consumer_key": str(source.get("daraja_consumer_key") or "").strip(),
        "daraja_consumer_secret": str(source.get("daraja_consumer_secret") or "").strip(),
        "daraja_shortcode": str(source.get("daraja_shortcode") or "").strip(),
        "daraja_passkey": str(source.get("daraja_passkey") or "").strip(),
        "daraja_till_number": str(source.get("daraja_till_number") or "").strip(),
        "daraja_environment": str(source.get("daraja_environment") or "production").strip(),
        "daraja_shortcode_type": str(source.get("daraja_shortcode_type") or "CustomerPayBillOnline").strip(),
    }


def _platform_only_daraja_config():
    # Prefer the explicit Daraja variable family. Only fall back to the older
    # MPESA aliases as a complete credential set for the selected environment.
    daraja_environment = str(os.getenv("DARAJA_ENVIRONMENT") or os.getenv("MPESA_ENVIRONMENT") or "production").strip().lower()
    sandbox = daraja_environment in {"sandbox", "test", "testing"}
    if sandbox:
        consumer_key = os.getenv("DARAJA_SANDBOX_CONSUMER_KEY") or os.getenv("MPESA_SANDBOX_CONSUMER_KEY") or os.getenv("MPESA_CONSUMER_KEY")
        consumer_secret = os.getenv("DARAJA_SANDBOX_CONSUMER_SECRET") or os.getenv("MPESA_SANDBOX_CONSUMER_SECRET") or os.getenv("MPESA_CONSUMER_SECRET")
        shortcode = os.getenv("DARAJA_SANDBOX_SHORTCODE") or os.getenv("MPESA_SANDBOX_SHORTCODE") or os.getenv("MPESA_SHORTCODE") or os.getenv("MPESA_BUSINESS_SHORTCODE")
        passkey = os.getenv("DARAJA_SANDBOX_PASSKEY") or os.getenv("MPESA_SANDBOX_PASSKEY") or os.getenv("MPESA_PASSKEY")
        till_number = os.getenv("DARAJA_SANDBOX_TILL_NUMBER") or os.getenv("MPESA_SANDBOX_TILL_NUMBER") or os.getenv("MPESA_TILL_NUMBER") or os.getenv("MPESA_BUSINESS_SHORTCODE")
        shortcode_type = os.getenv("DARAJA_SANDBOX_SHORTCODE_TYPE") or os.getenv("MPESA_SANDBOX_SHORTCODE_TYPE") or os.getenv("MPESA_SHORTCODE_TYPE")
    else:
        consumer_key = os.getenv("DARAJA_CONSUMER_KEY") or os.getenv("MPESA_LIVE_CONSUMER_KEY") or os.getenv("MPESA_CONSUMER_KEY")
        consumer_secret = os.getenv("DARAJA_CONSUMER_SECRET") or os.getenv("MPESA_LIVE_CONSUMER_SECRET") or os.getenv("MPESA_CONSUMER_SECRET")
        shortcode = os.getenv("DARAJA_SHORTCODE") or os.getenv("MPESA_LIVE_SHORTCODE") or os.getenv("MPESA_SHORTCODE") or os.getenv("MPESA_BUSINESS_SHORTCODE")
        passkey = os.getenv("DARAJA_PASSKEY") or os.getenv("MPESA_LIVE_PASSKEY") or os.getenv("MPESA_PASSKEY")
        till_number = os.getenv("DARAJA_TILL_NUMBER") or os.getenv("MPESA_LIVE_TILL_NUMBER") or os.getenv("MPESA_TILL_NUMBER") or os.getenv("MPESA_BUSINESS_SHORTCODE")
        shortcode_type = os.getenv("DARAJA_SHORTCODE_TYPE") or os.getenv("MPESA_LIVE_SHORTCODE_TYPE") or os.getenv("MPESA_SHORTCODE_TYPE")
    return {
        "daraja_consumer_key": consumer_key,
        "daraja_consumer_secret": consumer_secret,
        "daraja_shortcode": shortcode,
        "daraja_passkey": passkey,
        "daraja_till_number": till_number,
        "daraja_environment": daraja_environment,
        "daraja_shortcode_type": shortcode_type or "CustomerPayBillOnline",
    }


def platform_daraja_config(tenant=None, payment_method=None):
    tenant = tenant or {}
    method = selected_daraja_method_raw(tenant, payment_method)
    tenant_config = _clean_daraja_config(tenant)
    platform_config = _clean_daraja_config(_platform_only_daraja_config())
    if daraja_is_configured(tenant_config, method):
        source = "tenant"
        config = tenant_config
    else:
        source = "platform"
        config = platform_config
    return {
        **tenant,
        **config,
        "daraja_credential_source": source,
    }


def tenant_payout_details(tenant):
    tenant = tenant or {}
    return {
        "business_number": str(tenant.get("business_number") or "").strip(),
        "bank_code": str(tenant.get("bank_code") or "").strip(),
        "bank_name": str(tenant.get("bank_name") or "").strip(),
        "bank_account_number": str(tenant.get("bank_account_number") or "").strip(),
        "bank_daraja_shortcode": str(tenant.get("bank_daraja_shortcode") or "").strip(),
        "daraja_settlement_till_number": str(tenant.get("daraja_settlement_till_number") or "").strip(),
        "settlement_destination_type": str(tenant.get("settlement_destination_type") or ("till" if tenant.get("daraja_settlement_till_number") else "bank")).strip().lower(),
        "payout_phone": str(tenant.get("payout_phone") or tenant.get("phone") or "").strip(),
    }


def daraja_b2b_settlement_status(tenant):
    tenant = tenant or {}
    payout = tenant_payout_details(tenant)
    method = selected_daraja_method(tenant)
    if str(tenant.get("payment_provider") or "").strip().lower() in {"mpesa", "daraja"} and daraja_is_configured(_clean_daraja_config(tenant), method):
        # Tenant-owned STK collections settle to the tenant's own shortcode.
        return "withdrawal_ready"
    if payout["settlement_destination_type"] == "phone":
        if not payout["payout_phone"]:
            return "missing_payout_destination"
        platform_config = _clean_daraja_config(_platform_only_daraja_config())
        has_b2c_credentials = bool(
            (os.getenv("DARAJA_B2C_SHORTCODE") or platform_config.get("daraja_shortcode"))
            and os.getenv("DARAJA_B2C_INITIATOR_NAME")
            and os.getenv("DARAJA_B2C_SECURITY_CREDENTIAL")
            and platform_config.get("daraja_consumer_key")
            and platform_config.get("daraja_consumer_secret")
        )
        return "withdrawal_ready" if has_b2c_credentials else "missing_b2c_credentials"
    if payout["settlement_destination_type"] == "till":
        has_destination = bool(payout["daraja_settlement_till_number"])
    else:
        has_destination = bool(payout["bank_daraja_shortcode"] and payout["bank_account_number"])
    if not has_destination:
        return "missing_b2b_destination"
    has_b2b_credentials = bool(
        os.getenv("DARAJA_B2B_SHORTCODE")
        and os.getenv("DARAJA_B2B_INITIATOR_NAME")
        and os.getenv("DARAJA_B2B_SECURITY_CREDENTIAL")
        and _clean_daraja_config(_platform_only_daraja_config()).get("daraja_consumer_key")
        and _clean_daraja_config(_platform_only_daraja_config()).get("daraja_consumer_secret")
    )
    return "withdrawal_ready" if has_b2b_credentials else "missing_b2b_credentials"


def daraja_is_configured(tenant, payment_method=None):
    tenant = tenant or {}
    common = all(str(tenant.get(field) or "").strip() for field in ("daraja_consumer_key", "daraja_consumer_secret", "daraja_passkey"))
    if payment_method == "daraja_buygoods":
        return common and all(str(tenant.get(field) or "").strip() for field in ("daraja_shortcode", "daraja_till_number"))
    return common and bool(str(tenant.get("daraja_shortcode") or "").strip())


def tenant_uses_daraja(tenant):
    return daraja_is_configured(platform_daraja_config(tenant), selected_daraja_method(tenant))


def selected_daraja_method_raw(tenant, requested_method=None):
    tenant = tenant or {}
    requested = str(requested_method or "").strip().lower()
    if requested in {"paybill", "mpesa_paybill"}:
        return "daraja_paybill"
    if requested in {"buygoods", "buy_goods", "mpesa_buygoods"}:
        return "daraja_buygoods"
    if requested in {"daraja_paybill", "daraja_buygoods"}:
        return requested
    methods = tenant.get("payment_methods") if isinstance(tenant.get("payment_methods"), list) else []
    selected = ""
    for item in methods:
        value = str(item).strip().lower()
        if value in {"paybill", "mpesa_paybill"}:
            selected = "daraja_paybill"
            break
        if value in {"buygoods", "buy_goods", "mpesa_buygoods"}:
            selected = "daraja_buygoods"
            break
        if value in {"daraja_paybill", "daraja_buygoods"}:
            selected = value
            break
    if selected:
        return selected
    shortcode_type = str(tenant.get("daraja_shortcode_type") or "").strip().lower()
    if shortcode_type == "customerbuygoodsonline":
        return "daraja_buygoods"
    if shortcode_type == "customerpaybillonline":
        return "daraja_paybill"
    default_method = str(os.getenv("DARAJA_DEFAULT_METHOD") or "").strip().lower()
    if default_method in {"daraja_paybill", "daraja_buygoods"}:
        return default_method
    return "daraja_paybill"


def selected_daraja_method(tenant, requested_method=None):
    return selected_daraja_method_raw(tenant, requested_method)


def daraja_environment_name(tenant):
    environment = str((tenant or {}).get("daraja_environment") or "production").strip().lower()
    return "sandbox" if environment in {"sandbox", "test", "testing"} else "production"


def daraja_base_url(tenant):
    return "https://api.safaricom.co.ke" if daraja_environment_name(tenant) == "production" else "https://sandbox.safaricom.co.ke"


def get_daraja_credentials(tenant, payment_method="daraja_paybill"):
    tenant = platform_daraja_config(tenant, payment_method)
    consumer_key = str(tenant.get("daraja_consumer_key") or "").strip()
    consumer_secret = str(tenant.get("daraja_consumer_secret") or "").strip()
    shortcode = str(tenant.get("daraja_shortcode") or "").strip()
    passkey = str(tenant.get("daraja_passkey") or "").strip()
    till_number = str(tenant.get("daraja_till_number") or "").strip()
    shortcode_type = str(tenant.get("daraja_shortcode_type") or "CustomerPayBillOnline").strip()
    shortcode_type_method = "daraja_buygoods" if shortcode_type.lower() == "customerbuygoodsonline" else "daraja_paybill"
    if payment_method not in {"daraja_paybill", "daraja_buygoods"}:
        payment_method = shortcode_type_method
    business_number = shortcode
    till_required = payment_method == "daraja_buygoods"
    if not all([consumer_key, consumer_secret, business_number, passkey]):
        logger.warning(
            "Daraja credentials incomplete for tenant=%s method=%s missing=%s",
            tenant.get("id"),
            payment_method,
            [
                name
                for name, value in {
                    "consumer_key": consumer_key,
                    "consumer_secret": consumer_secret,
                    "business_number": business_number,
                    "passkey": passkey,
                }.items()
                if not value
            ],
        )
        raise PaymentProviderError(
            "M-Pesa is not set up for this business yet. Please contact support.",
            "Tenant is missing one or more Daraja credentials",
            503,
        )
    if till_required and not till_number:
        logger.warning("Daraja Buy Goods till number missing for tenant=%s", tenant.get("id"))
        raise PaymentProviderError(
            "M-Pesa Buy Goods is not set up for this business yet. Please contact support.",
            "Tenant is missing Daraja Buy Goods till number",
            503,
        )
    return {
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret,
        "shortcode": shortcode,
        "passkey": passkey,
        "till_number": till_number,
        "shortcode_type": shortcode_type,
    }


def get_daraja_access_token(tenant, payment_method="daraja_paybill", require_stk_credentials=True):
    if require_stk_credentials:
        creds = get_daraja_credentials(tenant, payment_method)
    else:
        configured = platform_daraja_config(tenant, payment_method)
        consumer_key = str(configured.get("daraja_consumer_key") or "").strip()
        consumer_secret = str(configured.get("daraja_consumer_secret") or "").strip()
        if not consumer_key or not consumer_secret:
            raise PaymentProviderError("Daraja API credentials are incomplete.", "Missing Daraja consumer key or consumer secret", 503)
        creds = {"consumer_key": consumer_key, "consumer_secret": consumer_secret}
    response = requests.get(
        f"{daraja_base_url(tenant)}/oauth/v1/generate?grant_type=client_credentials",
        auth=(creds["consumer_key"], creds["consumer_secret"]),
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        logger.warning(
            "Daraja OAuth failed for tenant=%s method=%s status=%s response=%s",
            (tenant or {}).get("id"),
            payment_method,
            response.status_code,
            response.text[:500],
        )
        raise PaymentProviderError(
            "M-Pesa is temporarily unavailable. Please try again shortly.",
            f"Daraja OAuth failed {response.status_code}: {response.text[:500]}",
            503,
        ) from exc
    try:
        token = response.json().get("access_token")
    except ValueError as exc:
        logger.warning(
            "Daraja OAuth returned invalid JSON for tenant=%s method=%s status=%s response=%s",
            (tenant or {}).get("id"),
            payment_method,
            response.status_code,
            response.text[:500],
        )
        raise PaymentProviderError(
            "M-Pesa is temporarily unavailable. Please try again shortly.",
            f"Daraja OAuth returned invalid JSON: {response.text[:500]}",
            503,
        ) from exc
    if not token:
        logger.warning("Daraja OAuth returned no access token for tenant=%s method=%s", (tenant or {}).get("id"), payment_method)
        raise PaymentProviderError("M-Pesa is temporarily unavailable. Please try again shortly.", "Daraja OAuth returned no access_token", 503)
    return token


def daraja_timestamp_and_password(shortcode, passkey):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()
    return timestamp, password


def make_daraja_callback_token(tenant_id, payment_id):
    """Daraja callbacks carry an unguessable per-payment HMAC token."""
    digest = hmac.new(settings.SECRET_KEY.encode(), f"{tenant_id}:{payment_id}".encode(), hashlib.sha256).hexdigest()
    return digest[:32]


def verify_daraja_callback_token(tenant_id, payment_id, token):
    expected = make_daraja_callback_token(tenant_id, payment_id)
    return hmac.compare_digest(expected, str(token or ""))


def daraja_phone_format(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("7") and len(digits) == 9:
        digits = "254" + digits
    return digits


def initiate_daraja_payment(tenant, payment_id, amount, phone, description=None, metadata=None, payment_method="daraja_paybill"):
    payment_method = selected_daraja_method(tenant, payment_method)
    tenant = platform_daraja_config(tenant, payment_method)
    creds = get_daraja_credentials(tenant, payment_method)
    shortcode_type = str(creds.get("shortcode_type") or "CustomerPayBillOnline").strip()
    if payment_method not in {"daraja_paybill", "daraja_buygoods"}:
        payment_method = "daraja_buygoods" if shortcode_type.lower() == "customerbuygoodsonline" else "daraja_paybill"
    tenant_id = (tenant or {}).get("id")
    formatted_phone = daraja_phone_format(phone)
    if not formatted_phone or not formatted_phone.startswith("254") or len(formatted_phone) != 12:
        logger.info("Daraja STK rejected invalid phone for tenant=%s payment=%s method=%s phone=%s", tenant_id, payment_id, payment_method, phone)
        raise PaymentProviderError("Enter a valid M-Pesa phone number (07XXXXXXXX or 2547XXXXXXXX).", "Invalid phone for Daraja STK push", 400)

    base_url = get_public_base_url()
    if not base_url:
        logger.error("Daraja callback base URL missing for tenant=%s payment=%s", tenant_id, payment_id)
        raise RuntimeError("PUBLIC_APP_URL or DARAJA_CALLBACK_BASE_URL is required for the Daraja callback URL")

    token = get_daraja_access_token(tenant, payment_method)
    business_shortcode = creds["shortcode"]
    timestamp, password = daraja_timestamp_and_password(business_shortcode, creds["passkey"])
    callback_token = make_daraja_callback_token(tenant_id, payment_id)
    callback_url = f"{base_url}/api/daraja/callback/{tenant_id}/{payment_id}/{callback_token}"

    party_b = creds["till_number"] if payment_method == "daraja_buygoods" else business_shortcode
    transaction_type = "CustomerBuyGoodsOnline" if payment_method == "daraja_buygoods" else "CustomerPayBillOnline"
    logger.info(
        "Daraja STK config tenant=%s payment=%s environment=%s method=%s shortcode=%s transaction_type=%s callback_base_set=%s",
        tenant_id,
        payment_id,
        tenant.get("daraja_environment"),
        payment_method,
        business_shortcode,
        transaction_type,
        bool(base_url),
    )
    payload = {
        "BusinessShortCode": business_shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": max(1, int(round(float(amount or 0)))),
        "PartyA": formatted_phone,
        "PartyB": party_b,
        "PhoneNumber": formatted_phone,
        "CallBackURL": callback_url,
        "AccountReference": str((tenant or {}).get("business_name") or tenant_id)[:12],
        "TransactionDesc": (description or "Internet package")[:13],
    }

    response = requests.post(
        f"{daraja_base_url(tenant)}/mpesa/stkpush/v1/processrequest",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        logger.warning(
            "Daraja STK push failed for tenant=%s payment=%s method=%s status=%s response=%s",
            tenant_id,
            payment_id,
            payment_method,
            response.status_code,
            response.text[:500],
        )
        raise PaymentProviderError(
            "Could not start the M-Pesa payment. Please try again.",
            f"Daraja STK push failed {response.status_code}: {response.text[:500]}",
            502,
        ) from exc
    try:
        data = response.json()
    except ValueError as exc:
        logger.warning(
            "Daraja STK returned invalid JSON for tenant=%s payment=%s method=%s status=%s response=%s",
            tenant_id,
            payment_id,
            payment_method,
            response.status_code,
            response.text[:500],
        )
        raise PaymentProviderError(
            "Could not start the M-Pesa payment. Please try again.",
            f"Daraja returned invalid JSON: {response.text[:500]}",
            502,
        ) from exc
    if str(data.get("ResponseCode") or "0") not in {"0", "00"} and not data.get("CheckoutRequestID"):
        logger.warning("Daraja rejected STK push for tenant=%s payment=%s method=%s response=%s", tenant_id, payment_id, payment_method, data)
        raise PaymentProviderError(
            "Could not start the M-Pesa payment. Please try again.",
            f"Daraja rejected STK push: {data}",
            502,
        )
    if str(data.get("ResponseCode")) != "0":
        logger.warning("Daraja STK non-success response for tenant=%s payment=%s method=%s response=%s", tenant_id, payment_id, payment_method, data)
        raise PaymentProviderError(
            "Could not start the M-Pesa payment. Please try again.",
            f"Daraja rejected STK push: {data}",
            502,
        )
    logger.info(
        "Daraja STK push started for tenant=%s payment=%s method=%s checkout=%s merchant=%s callback_url=%s",
        tenant_id,
        payment_id,
        payment_method,
        data.get("CheckoutRequestID"),
        data.get("MerchantRequestID"),
        callback_url,
    )
    return {
        "checkout_request_id": data.get("CheckoutRequestID"),
        "merchant_request_id": data.get("MerchantRequestID"),
        "phone": formatted_phone,
        "customer_message": data.get("CustomerMessage"),
        "callback_url": callback_url,
    }


def query_daraja_stk_payment(tenant, checkout_request_id, payment_method="daraja_paybill"):
    payment_method = selected_daraja_method(tenant, payment_method)
    tenant = platform_daraja_config(tenant, payment_method)
    creds = get_daraja_credentials(tenant, payment_method)
    token = get_daraja_access_token(tenant, payment_method)
    timestamp, password = daraja_timestamp_and_password(creds["shortcode"], creds["passkey"])
    payload = {
        "BusinessShortCode": creds["shortcode"],
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }
    response = requests.post(
        f"{daraja_base_url(tenant)}/mpesa/stkpushquery/v1/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        logger.warning(
            "Daraja STK query failed for tenant=%s checkout=%s status=%s response=%s",
            (tenant or {}).get("id"),
            checkout_request_id,
            response.status_code,
            response.text[:500],
        )
        raise PaymentProviderError(
            "Payment verification is temporarily unavailable. Please wait a moment.",
            f"Daraja STK query failed {response.status_code}: {response.text[:500]}",
            503,
        ) from exc
    try:
        return response.json()
    except ValueError as exc:
        raise PaymentProviderError(
            "Payment verification is temporarily unavailable. Please wait a moment.",
            f"Daraja STK query returned invalid JSON: {response.text[:500]}",
            503,
        ) from exc


def initiate_daraja_b2c(tenant, payment_id, amount, phone, remarks=None, originator_id=None):
    tenant = platform_daraja_config(tenant)
    shortcode = str(tenant.get("daraja_b2c_shortcode") or os.getenv("DARAJA_B2C_SHORTCODE") or tenant.get("daraja_shortcode") or "").strip()
    initiator = str(tenant.get("daraja_b2c_initiator_name") or os.getenv("DARAJA_B2C_INITIATOR_NAME") or "").strip()
    security_credential = str(tenant.get("daraja_b2c_security_credential") or os.getenv("DARAJA_B2C_SECURITY_CREDENTIAL") or "").strip()
    recipient = daraja_phone_format(phone)
    if not all([shortcode, initiator, security_credential]):
        raise PaymentProviderError(
            "Tenant settlement is not fully configured.",
            "Missing Daraja B2C shortcode, initiator name, or security credential",
            503,
        )
    if not recipient or not recipient.startswith("254") or len(recipient) != 12:
        raise PaymentProviderError("Tenant payout phone is invalid.", "Invalid Daraja B2C recipient phone", 400)

    base_url = get_public_base_url()
    if not base_url:
        raise RuntimeError("PUBLIC_APP_URL or DARAJA_CALLBACK_BASE_URL is required for Daraja B2C callbacks")

    token = get_daraja_access_token(tenant, require_stk_credentials=False)
    payload = {
        "OriginatorConversationID": str(originator_id or f"SET{secrets.token_hex(8).upper()}")[:20],
        "InitiatorName": initiator,
        "SecurityCredential": security_credential,
        "CommandID": str(os.getenv("DARAJA_B2C_COMMAND_ID") or "BusinessPayment"),
        "Amount": max(1, int(round(float(amount or 0)))),
        "PartyA": shortcode,
        "PartyB": recipient,
        "Remarks": str(remarks or f"Tenant settlement {payment_id}")[:100],
        "QueueTimeOutURL": f"{base_url}/api/daraja/b2c/timeout",
        "ResultURL": f"{base_url}/api/daraja/b2c/result",
        "Occasion": str(payment_id)[:100],
    }
    response = requests.post(
        f"{daraja_base_url(tenant)}/mpesa/b2c/v3/paymentrequest",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise PaymentProviderError(
            "Tenant settlement could not be requested.",
            f"Daraja B2C request failed {response.status_code}: {response.text[:500]}",
            502,
        ) from exc
    data = response.json()
    if str(data.get("ResponseCode")) not in {"0", "00"}:
        raise PaymentProviderError(
            "Tenant settlement could not be requested.",
            data.get("ResponseDescription") or data.get("errorMessage") or f"Daraja B2C rejected request: {data}",
            502,
        )
    data.setdefault("OriginatorConversationID", payload["OriginatorConversationID"])
    return data


def initiate_daraja_b2b_settlement(tenant, payment_id, amount, destination_type, recipient_shortcode, account_number="", remarks=None, originator_id=None):
    """Send a tenant settlement to a bank Paybill/account or a Buy Goods till."""
    tenant_id = (tenant or {}).get("id")
    tenant = {**_clean_daraja_config(_platform_only_daraja_config()), "id": tenant_id}
    shortcode = str(os.getenv("DARAJA_B2B_SHORTCODE") or "").strip()
    initiator = str(os.getenv("DARAJA_B2B_INITIATOR_NAME") or "").strip()
    security_credential = str(os.getenv("DARAJA_B2B_SECURITY_CREDENTIAL") or "").strip()
    recipient_shortcode = "".join(ch for ch in str(recipient_shortcode or "") if ch.isdigit())
    account_reference = str(account_number or "").strip()
    destination_type = str(destination_type or "").strip().lower()
    if destination_type not in {"bank", "till"}:
        destination_type = "bank"
    if not all((shortcode, initiator, security_credential, recipient_shortcode)):
        raise PaymentProviderError(
            "B2B settlement is not fully configured.",
            "B2B requires a sender shortcode, B2B initiator credentials, and a receiving bank Paybill shortcode or Buy Goods till",
            503,
        )
    if len(shortcode) < 5 or len(shortcode) > 10 or len(recipient_shortcode) < 5 or len(recipient_shortcode) > 10 or (destination_type == "bank" and not account_reference):
        raise PaymentProviderError("The B2B settlement destination is invalid.", "Invalid recipient shortcode or bank account reference", 400)

    base_url = get_public_base_url()
    if not base_url:
        raise RuntimeError("PUBLIC_APP_URL or DARAJA_CALLBACK_BASE_URL is required for Daraja B2B callbacks")

    token = get_daraja_access_token(tenant, require_stk_credentials=False)
    originator_id = str(originator_id or f"SET{secrets.token_hex(8).upper()}")[:20]
    is_till = destination_type == "till"
    payload = {
        "Initiator": initiator,
        "SecurityCredential": security_credential,
        "CommandID": "BusinessBuyGoods" if is_till else "BusinessPayBill",
        "SenderIdentifierType": str(os.getenv("DARAJA_B2B_SENDER_IDENTIFIER_TYPE") or "4"),
        "RecieverIdentifierType": str(os.getenv("DARAJA_B2B_TILL_IDENTIFIER_TYPE") or "2") if is_till else str(os.getenv("DARAJA_B2B_RECEIVER_IDENTIFIER_TYPE") or "4"),
        "Amount": max(1, int(round(float(amount or 0)))),
        "PartyA": shortcode,
        "PartyB": recipient_shortcode,
        "AccountReference": account_reference if not is_till else "",
        "Remarks": str(remarks or f"Tenant settlement {payment_id}")[:100],
        "QueueTimeOutURL": f"{base_url}/api/daraja/b2b/timeout",
        "ResultURL": f"{base_url}/api/daraja/b2b/result",
        "OriginatorConversationID": originator_id,
    }
    if is_till:
        payload.pop("AccountReference", None)
    response = requests.post(
        f"{daraja_base_url(tenant)}/mpesa/b2b/v1/paymentrequest",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    try:
        response.raise_for_status()
        data = response.json()
    except (requests.HTTPError, ValueError) as exc:
        raise PaymentProviderError(
            "B2B settlement could not be requested.",
            f"Daraja B2B request failed ({response.status_code}): {response.text[:500]}",
            502,
        ) from exc
    if str(data.get("ResponseCode")) not in {"0", "00"}:
        raise PaymentProviderError(
            "B2B settlement could not be requested.",
            data.get("ResponseDescription") or data.get("errorMessage") or f"Daraja B2B rejected request: {data}",
            502,
        )
    data.setdefault("OriginatorConversationID", originator_id)
    return data



def platform_notification_settings():
    try:
        return ref("site_settings").get() or {}
    except Exception:
        return {}


def whatsapp_enabled(tenant=None):
    if tenant and "whatsapp_enabled" in tenant:
        return tenant.get("whatsapp_enabled") is not False
    platform = platform_notification_settings()
    if "whatsapp_enabled" in platform:
        return platform.get("whatsapp_enabled") is not False
    return os.getenv("WHATSAPP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def apiwap_config(tenant=None):
    platform = platform_notification_settings()
    api_url = str(
        (tenant or {}).get("apiwap_base_url")
        or platform.get("apiwap_base_url")
        or os.getenv("APIWAP_API_URL")
        or os.getenv("APIWAP_BASE_URL")
        or "https://api.apiwap.com/api/v1"
    ).strip()
    if not api_url.rstrip("/").endswith("/whatsapp/send-message"):
        api_url = f"{api_url.rstrip('/')}/whatsapp/send-message"
    return {
        "enabled": (tenant or {}).get("whatsapp_enabled", True) is not False,
        "api_url": api_url,
        "api_key": str((tenant or {}).get("apiwap_api_key") or platform.get("apiwap_api_key") or os.getenv("APIWAP_TOKEN") or os.getenv("APIWAP_API_KEY") or "").strip(),
    }


def slek_config():
    return {
        "api_url": str(os.getenv("SLEK_API_URL") or "https://slek.org/whatsapp").strip(),
        "key": str(os.getenv("SLEK_KEY") or "").strip(),
        "secret": str(os.getenv("SLEK_SECRET") or "").strip(),
    }


def check_dns(host):
    try:
        socket.gethostbyname(host)
        return True
    except socket.gaierror:
        return False


def normalize_kenyan_whatsapp_number(phone):
    recipient = normalize_phone(phone)
    if not recipient:
        raise ValueError("Phone number is empty")
    if not re.fullmatch(r"254(7|1)\d{8}", recipient):
        raise ValueError(f"Invalid Kenyan phone number after normalization: {recipient}")
    return f"+{recipient}"


def normalize_kenyan_whatsapp_number_plain(phone):
    recipient = normalize_phone(phone)
    if not recipient:
        raise ValueError("Phone number is empty")
    if not re.fullmatch(r"254(7|1)\d{8}", recipient):
        raise ValueError(f"Invalid Kenyan phone number after normalization: {recipient}")
    return recipient


def send_slek_whatsapp_message(phone, message, tenant=None, recipient_name=None, header=None):
    config = slek_config()
    if not config["key"] or not config["secret"] or not config["api_url"]:
        return {"sent": False, "provider": "slek", "skipped": "missing_credentials"}
    try:
        recipient = normalize_kenyan_whatsapp_number_plain(phone)
    except ValueError as exc:
        return {"sent": False, "provider": "slek", "skipped": "invalid_phone", "error": str(exc)}
    try:
        response = requests.post(
            config["api_url"],
            data={
                "slek_key": config["key"],
                "slek_secret": config["secret"],
                "header": header or (tenant or {}).get("business_name") or "Expressnet",
                "message": str(message or ""),
                "recipient_phone": recipient,
                "recipient_name": recipient_name or "Customer",
            },
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=30,
        )
        response.raise_for_status()
        return {"sent": True, "provider": "slek", "recipient": recipient, "response": response.text}
    except requests.exceptions.RequestException as exc:
        return {"sent": False, "provider": "slek", "recipient": recipient, "error": str(exc)}


def _post_apiwap_whatsapp(config, recipient, message):
    host = urlparse(config["api_url"]).hostname or "api.apiwap.com"
    if not check_dns(host):
        raise requests.exceptions.ConnectionError(
            f"Could not resolve '{host}'. This is a local network/DNS issue, not an API key problem."
        )
    response = requests.post(
        config["api_url"],
        json={
            "phoneNumber": recipient,
            "message": str(message or ""),
            "type": "text",
        },
        headers={"Authorization": f"Bearer {config['api_key']}"},
        timeout=15,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    return payload


def send_whatsapp_message(phone, message, tenant=None, recipient_name=None, header=None):
    if not whatsapp_enabled(tenant):
        return {"sent": False, "skipped": "disabled"}
    platform = platform_notification_settings()
    provider = str((tenant or {}).get("notification_provider") or platform.get("notification_provider") or os.getenv("WHATSAPP_PROVIDER") or "slek").strip().lower()
    if provider in {"slek", "default", "expressnet"}:
        return send_slek_whatsapp_message(phone, message, tenant, recipient_name=recipient_name, header=header)
    if provider not in {"apiwap", "apiwap_whatsapp"}:
        return {"sent": False, "skipped": "unsupported_provider"}

    config = apiwap_config(tenant)
    if not config["enabled"]:
        return {"sent": False, "skipped": "disabled"}
    if not config["api_key"] or not config["api_url"]:
        return {"sent": False, "skipped": "missing_credentials"}

    try:
        recipient = normalize_kenyan_whatsapp_number(phone)
    except ValueError as exc:
        return {"sent": False, "skipped": "invalid_phone", "error": str(exc)}

    try:
        payload = _post_apiwap_whatsapp(config, recipient, message)
        return {"sent": True, "provider": "apiwap", "recipient": recipient, "response": payload}
    except requests.exceptions.RequestException as exc:
        return {"sent": False, "provider": "apiwap", "recipient": recipient, "error": str(exc)}


def send_sms_message(phone, message, tenant=None):
    """Send through the shared SMS gateway; a tenant sender ID is optional."""
    if tenant and tenant.get("sms_enabled") is False:
        return {"sent": False, "skipped": "disabled"}
    api_url = (os.getenv("SMS_API_URL") or os.getenv("ROAMTECH_API_URL") or "").strip()
    token = os.getenv("SMS_API_TOKEN") or os.getenv("ROAMTECH_API_TOKEN") or os.getenv("ROAMTECH_TOKEN")
    recipient = normalize_phone(phone)
    if not recipient:
        return {"sent": False, "skipped": "missing_phone"}
    if not api_url or not token:
        return {"sent": False, "skipped": "missing_credentials"}
    sender = str((tenant or {}).get("roamtech_sender_id") or os.getenv("SMS_DEFAULT_SENDER_ID") or os.getenv("ROAMTECH_DEFAULT_SENDER_ID") or "EXPRESS WIFI").strip()
    response = requests.post(api_url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"to": recipient, "message": str(message or ""), "from": sender, "sender_id": sender}, timeout=20)
    response.raise_for_status()
    return {"sent": True, "response": response.json() if response.content else {}}


