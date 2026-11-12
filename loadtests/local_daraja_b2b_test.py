"""Local-only Daraja STK-to-B2B settlement test.

This script is deliberately isolated from the Django application and reads
only ``DARAJA_TEST_*`` environment variables.  It cannot accidentally use
the application's payment or settlement credentials.

It has two explicit stages:

1. ``stk`` sends an STK prompt to the supplied phone.
2. ``settle`` first verifies that STK payment, then sends B2B to the supplied
   bank Paybill/account only when both the provider result is successful and
   ``--confirm-live`` is present.

Do not commit credentials.  For a production B2B test, provide a public HTTPS
callback URL (for example, an authorised tunnel to your local listener).  The
initial B2B acknowledgement is not the final settlement result.
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


LOG_PATH = Path(__file__).with_name("daraja_b2b_test.log")
# An optional, ignored test-only file makes it possible to run the isolated
# test without copying payment credentials into the application's .env.
load_dotenv(Path(__file__).with_name(".env.daraja-test"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("local_daraja_b2b_test")


def env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def safe_phone(value: str) -> str:
    return f"***{value[-4:]}" if len(value) >= 4 else "***"


def normalized_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = f"254{digits[1:]}"
    elif digits.startswith("7") and len(digits) == 9:
        digits = f"254{digits}"
    if not digits.startswith("254") or len(digits) != 12:
        raise ValueError("Phone must be Kenyan format 07XXXXXXXX or 2547XXXXXXXX.")
    return digits


def api_base(environment: str) -> str:
    return "https://api.safaricom.co.ke" if environment == "production" else "https://sandbox.safaricom.co.ke"


def access_token(base_url: str, key_name: str, secret_name: str) -> str:
    logger.info("Requesting Daraja OAuth token using %s/%s", key_name, secret_name)
    response = requests.get(
        f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
        auth=(env(key_name), env(secret_name)),
        timeout=20,
    )
    response.raise_for_status()
    token = str(response.json().get("access_token") or "")
    if not token:
        raise RuntimeError("Daraja OAuth response did not contain an access token.")
    return token


def post(base_url: str, endpoint: str, token: str, payload: dict) -> dict:
    logger.info("Submitting Daraja request endpoint=%s", endpoint)
    response = requests.post(
        f"{base_url}{endpoint}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if str(body.get("ResponseCode") or "") not in {"0", "00"}:
        logger.error("Daraja rejected endpoint=%s response=%s", endpoint, body.get("ResponseDescription") or body.get("errorMessage") or "no description")
        raise RuntimeError(f"Daraja rejected the request: {body.get('ResponseDescription') or body.get('errorMessage') or body}")
    logger.info("Daraja acknowledged endpoint=%s conversation_id=%s checkout_id=%s", endpoint, body.get("ConversationID"), body.get("CheckoutRequestID"))
    return body


def send_stk(base_url: str, amount: int, phone: str, callback_base: str) -> dict:
    logger.info("Starting STK test amount=KES %s phone=%s callback=%s", amount, safe_phone(phone), callback_base)
    shortcode = env("DARAJA_TEST_STK_SHORTCODE")
    passkey = env("DARAJA_TEST_STK_PASSKEY")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode("utf-8")).decode("ascii")
    token = access_token(base_url, "DARAJA_TEST_STK_CONSUMER_KEY", "DARAJA_TEST_STK_CONSUMER_SECRET")
    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": env("DARAJA_TEST_STK_TRANSACTION_TYPE"),
        "Amount": amount,
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": f"{callback_base}/api/daraja/test/stk-result",
        "AccountReference": "LOCALB2BTEST",
        "TransactionDesc": "Local B2B test",
    }
    return post(base_url, "/mpesa/stkpush/v1/processrequest", token, payload)


def verify_stk(base_url: str, checkout_request_id: str) -> dict:
    logger.info("Verifying STK checkout_id=%s", checkout_request_id)
    shortcode = env("DARAJA_TEST_STK_SHORTCODE")
    passkey = env("DARAJA_TEST_STK_PASSKEY")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode("utf-8")).decode("ascii")
    token = access_token(base_url, "DARAJA_TEST_STK_CONSUMER_KEY", "DARAJA_TEST_STK_CONSUMER_SECRET")
    response = requests.post(
        f"{base_url}/mpesa/stkpushquery/v1/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"BusinessShortCode": shortcode, "Password": password, "Timestamp": timestamp, "CheckoutRequestID": checkout_request_id},
        timeout=20,
    )
    response.raise_for_status()
    body = response.json()
    if str(body.get("ResultCode") or "") != "0":
        logger.warning("STK is not yet successful checkout_id=%s result_code=%s detail=%s", checkout_request_id, body.get("ResultCode"), body.get("ResultDesc"))
        raise RuntimeError(f"STK payment is not successful: {body.get('ResultDesc') or body}")
    logger.info("STK succeeded checkout_id=%s", checkout_request_id)
    return body


def settle_b2b(base_url: str, amount: int, paybill: str, account: str, callback_base: str) -> dict:
    logger.info("Starting B2B settlement amount=KES %s paybill=%s account=***%s callback=%s", amount, paybill, account[-4:], callback_base)
    token = access_token(base_url, "DARAJA_TEST_B2B_CONSUMER_KEY", "DARAJA_TEST_B2B_CONSUMER_SECRET")
    originator_id = f"LOCAL{datetime.now().strftime('%Y%m%d%H%M%S')}"
    payload = {
        "Initiator": env("DARAJA_TEST_B2B_INITIATOR_NAME"),
        "SecurityCredential": env("DARAJA_TEST_B2B_SECURITY_CREDENTIAL"),
        "CommandID": "BusinessPayBill",
        "SenderIdentifierType": "4",
        "RecieverIdentifierType": "4",
        "Amount": amount,
        "PartyA": env("DARAJA_TEST_B2B_SHORTCODE"),
        "PartyB": paybill,
        "AccountReference": account,
        "Remarks": "Local B2B test",
        "QueueTimeOutURL": f"{callback_base}/api/daraja/test/b2b-timeout",
        "ResultURL": f"{callback_base}/api/daraja/test/b2b-result",
        "OriginatorConversationID": originator_id,
    }
    return post(base_url, "/mpesa/b2b/v1/paymentrequest", token, payload)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local-only, confirmation-gated Daraja STK-to-B2B test")
    parser.add_argument("stage", choices=("stk", "settle"))
    parser.add_argument("--amount", type=int, required=True, help="Whole Kenyan shillings; must be positive.")
    parser.add_argument("--phone", help="STK recipient phone; required for the stk stage.")
    parser.add_argument("--checkout-request-id", help="Successful STK checkout ID; required for the settle stage.")
    parser.add_argument("--paybill", default="222111", help="Receiving bank Paybill shortcode.")
    parser.add_argument("--account", default="057000050061", help="Receiving bank account reference.")
    parser.add_argument("--bank-code", default="70", help="Recorded for operator verification; Daraja B2B has no BankCode request field.")
    parser.add_argument("--environment", choices=("sandbox", "production"), default="sandbox")
    parser.add_argument("--callback-base-url", default=os.getenv("DARAJA_TEST_CALLBACK_BASE_URL", ""))
    parser.add_argument("--confirm-live", action="store_true", help="Required for every network request.")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    if args.amount < 1:
        raise ValueError("Amount must be at least KES 1.")
    if not args.confirm_live:
        print("Dry run only. Add --confirm-live after verifying the amount, phone, Paybill and account.")
        return 0
    callback_base = args.callback_base_url.rstrip("/")
    if not callback_base.startswith("https://"):
        raise ValueError("--callback-base-url must be a public HTTPS URL so Daraja can deliver final results.")
    base_url = api_base(args.environment)
    if args.stage == "stk":
        if not args.phone:
            raise ValueError("--phone is required for the stk stage.")
        result = send_stk(base_url, args.amount, normalized_phone(args.phone), callback_base)
        print({"checkout_request_id": result.get("CheckoutRequestID"), "merchant_request_id": result.get("MerchantRequestID"), "customer_message": result.get("CustomerMessage")})
        return 0

    if not args.checkout_request_id:
        raise ValueError("--checkout-request-id is required for the settle stage.")
    verify_stk(base_url, args.checkout_request_id)
    result = settle_b2b(base_url, args.amount, args.paybill, args.account, callback_base)
    print({"status": "acknowledged", "conversation_id": result.get("ConversationID"), "originator_conversation_id": result.get("OriginatorConversationID"), "bank_code_verified_by_operator": args.bank_code})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        logger.exception("Daraja local test failed: %s", exc)
        logger.error("B2B checklist: confirm STK ResultCode is 0; verify production B2B product, shortcode, initiator and security credential; ensure the B2B utility account has funds; verify Paybill/account mapping; and keep the public callback URL reachable.")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
