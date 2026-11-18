from datetime import datetime
from decimal import Decimal
from unittest import TestCase

from app.parser.hsbc import parse_transaction


class HSBCParserTests(TestCase):
    def test_date_only_alert_uses_the_transaction_date_and_amount(self):
        html = (
            "<p>Your HSBC Credit Card <strong>xx1234</strong> was used for a transaction of"
            " INR&nbsp;1,241.00 at <strong>TEST STORE</strong> on 17/11/26.</p>"
            "<p>Available limit: INR 974233.57. Amount due: INR 16766.43.</p>"
        )

        transaction = parse_transaction("message-1", html)

        self.assertEqual(transaction.graph_message_id, "message-1")
        self.assertEqual(transaction.card_last4, "1234")
        self.assertEqual(transaction.currency, "INR")
        self.assertEqual(transaction.amount, Decimal("1241.00"))
        self.assertEqual(transaction.merchant, "TEST STORE")
        self.assertEqual(transaction.transaction_at, datetime(2026, 11, 17))
        self.assertEqual(
            parse_transaction("message-2", html.replace("17/11/26", "17/11/2026")),
            parse_transaction("message-2", html),
        )

    def test_legacy_alert_keeps_the_transaction_time(self):
        html = (
            "Your card ending with 1234 was used for INR 241.00 "
            "payment to TEST STORE on 9 Aug 2026 at 13:05."
        )

        self.assertEqual(
            parse_transaction("legacy", html).transaction_at, datetime(2026, 8, 9, 13, 5)
        )
        self.assertEqual(
            parse_transaction("legacy", html.replace("13:05", "24:00")).transaction_at,
            datetime(2026, 8, 10),
        )

    def test_statement_and_invalid_date_are_rejected(self):
        for html in (
            "Your HSBC Credit Card xx1234 statement is ready. Amount due: INR 241.00.",
            "HSBC Credit Card xx1234 was used for a transaction of INR 241.00 at "
            "TEST STORE on 31/11/26.",
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                parse_transaction("invalid", html)
