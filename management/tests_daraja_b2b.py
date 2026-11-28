import os
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from management.services.billing import (
    daraja_b2b_settlement_status,
    initiate_daraja_b2b_settlement,
)


class DarajaB2BSettlementTests(SimpleTestCase):
    @patch.dict(
        os.environ,
        {
            "DARAJA_B2B_UTILITY_SHORTCODE": "1395292",
            "DARAJA_B2B_WORKING_SHORTCODE": "600999",
            "DARAJA_B2B_INITIATOR_NAME": "utility-initiator",
            "DARAJA_B2B_SECURITY_CREDENTIAL": "credential",
            "DARAJA_B2B_SENDER_IDENTIFIER_TYPE": "4",
            "DARAJA_B2B_TILL_IDENTIFIER_TYPE": "2",
            "DARAJA_CALLBACK_BASE_URL": "https://callback.example.test",
            "MPESA_CONSUMER_KEY": "consumer-key",
            "MPESA_CONSUMER_SECRET": "consumer-secret",
        },
        clear=False,
    )
    @patch("management.services.billing.get_daraja_access_token", return_value="token")
    @patch("management.services.billing.requests.post")
    def test_buy_goods_settlement_uses_mmf_working_account_as_party_a(self, post, _token):
        response = Mock()
        response.json.return_value = {"ResponseCode": "0", "ConversationID": "conversation"}
        post.return_value = response

        initiate_daraja_b2b_settlement(
            {"id": "tenant-1"},
            "payment-1",
            2,
            "till",
            "1756849",
            originator_id="utility-test-1",
        )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["PartyA"], "600999")
        self.assertEqual(payload["PartyB"], "1756849")
        self.assertEqual(payload["CommandID"], "BusinessBuyGoods")
        self.assertNotIn("AccountReference", payload)

    @patch.dict(
        os.environ,
        {
            "DARAJA_B2B_WORKING_SHORTCODE": "600999",
            "DARAJA_B2B_INITIATOR_NAME": "working-initiator",
            "DARAJA_B2B_SECURITY_CREDENTIAL": "credential",
            "MPESA_CONSUMER_KEY": "consumer-key",
            "MPESA_CONSUMER_SECRET": "consumer-secret",
        },
        clear=False,
    )
    def test_bank_settlement_is_ready_after_auto_sweep_to_working_account(self):
        status = daraja_b2b_settlement_status({
            "settlement_destination_type": "bank",
            "bank_daraja_shortcode": "222111",
            "bank_account_number": "106108",
        })

        self.assertEqual(status, "withdrawal_ready")

    @patch("management.services.billing.get_daraja_access_token", return_value="token")
    @patch("management.services.billing.requests.post")
    @patch.dict(
        os.environ,
        {
            "DARAJA_B2B_WORKING_SHORTCODE": "600999",
            "DARAJA_B2B_INITIATOR_NAME": "working-initiator",
            "DARAJA_B2B_SECURITY_CREDENTIAL": "credential",
            "DARAJA_CALLBACK_BASE_URL": "https://callback.example.test",
            "MPESA_CONSUMER_KEY": "consumer-key",
            "MPESA_CONSUMER_SECRET": "consumer-secret",
        },
        clear=False,
    )
    def test_bank_settlement_is_sent_as_business_paybill_from_working_account(self, post, _token):
        response = Mock()
        response.json.return_value = {"ResponseCode": "0", "ConversationID": "conversation"}
        post.return_value = response

        initiate_daraja_b2b_settlement(
            {"id": "tenant-1"}, "payment-1", 2, "bank", "222111", "106108",
        )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["PartyA"], "600999")
        self.assertEqual(payload["PartyB"], "222111")
        self.assertEqual(payload["CommandID"], "BusinessPayBill")
        self.assertEqual(payload["AccountReference"], "106108")
