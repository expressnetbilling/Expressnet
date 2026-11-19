import os
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from management.services.billing import (
    PaymentProviderError,
    daraja_b2b_settlement_status,
    initiate_daraja_b2b_settlement,
)


class DarajaB2BSettlementTests(SimpleTestCase):
    @patch.dict(
        os.environ,
        {
            "DARAJA_B2B_UTILITY_SHORTCODE": "1395292",
            "DARAJA_B2B_SHORTCODE": "MMF-WORKING-ACCOUNT",
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
    def test_buy_goods_settlement_uses_utility_shortcode_as_party_a(self, post, _token):
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
        self.assertEqual(payload["PartyA"], "1395292")
        self.assertEqual(payload["PartyB"], "1756849")
        self.assertEqual(payload["CommandID"], "BusinessBuyGoods")
        self.assertNotIn("AccountReference", payload)

    def test_bank_settlement_requires_business_hub(self):
        status = daraja_b2b_settlement_status({
            "settlement_destination_type": "bank",
            "bank_daraja_shortcode": "222111",
            "bank_account_number": "106108",
        })

        self.assertEqual(status, "business_hub_bank_settlement_required")

    @patch("management.services.billing.requests.post")
    def test_bank_settlement_is_never_sent_as_business_paybill(self, post):
        with self.assertRaises(PaymentProviderError) as raised:
            initiate_daraja_b2b_settlement(
                {"id": "tenant-1"},
                "payment-1",
                2,
                "bank",
                "222111",
                "106108",
            )

        self.assertEqual(raised.exception.status_code, 409)
        post.assert_not_called()
