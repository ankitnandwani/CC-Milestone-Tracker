from datetime import date, datetime
from decimal import Decimal
from unittest import TestCase

from app.milestones import card_milestones
from app.parser.au import parse_transaction


class AUCardTests(TestCase):
    def test_purchase_alert_preserves_spend_and_local_time(self):
        html = (
            "<p>INR&nbsp;100,000.00 were spent on your AU Credit Card <b>xx1234</b>"
            " at TEST JEWELLER on 17-11-2026 at 12:41:26 am.</p>"
        )
        transaction = parse_transaction("au-alert", html)
        self.assertEqual(transaction.card_last4, "1234")
        self.assertEqual(transaction.currency, "INR")
        self.assertEqual(transaction.amount, Decimal("100000.00"))
        self.assertEqual(transaction.merchant, "TEST JEWELLER")
        self.assertEqual(transaction.transaction_at, datetime(2026, 11, 17, 0, 41, 26))
        self.assertEqual(
            parse_transaction("au-alert", html.replace("am.", "pm.")).transaction_at,
            datetime(2026, 11, 17, 12, 41, 26),
        )

    def test_annual_milestones_roll_over_on_november_12(self):
        before = card_milestones("AU", "3052", date(2026, 11, 11))
        after = card_milestones("AU", "3052", date(2026, 11, 12))
        self.assertEqual(before[0][2:], (datetime(2025, 11, 12), datetime(2026, 11, 12)))
        self.assertEqual(after[0][2:], (datetime(2026, 11, 12), datetime(2027, 11, 12)))
        self.assertEqual(after[0][2:], after[1][2:])
        self.assertEqual([item[1] for item in after], [800000, 1200000, 75000])

    def test_monthly_milestone_rolls_over_after_statement_day(self):
        closing = card_milestones("AU", "3052", date(2026, 12, 23))[-1]
        opening = card_milestones("AU", "3052", date(2026, 12, 24))[-1]
        self.assertEqual(closing[2:], (datetime(2026, 11, 24), datetime(2026, 12, 24)))
        self.assertEqual(opening[2:], (datetime(2026, 12, 24), datetime(2027, 1, 24)))

    def test_hsbc_retains_its_existing_target_and_window(self):
        self.assertEqual(
            card_milestones("HSBC", "2677", date(2026, 11, 19))[0][1:],
            (Decimal("1200000"), datetime(2026, 6, 13), datetime(2027, 6, 13)),
        )
