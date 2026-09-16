"""
backend/tests/test_services/test_purchase_validator.py

Unit tests for PurchaseValidator covering constraints, dates, options, and error handling.
"""
from datetime import date
from decimal import Decimal
import unittest

from backend.services.errors import InvalidPurchaseError
from backend.services.purchase_validator import PurchaseValidator
from buyorwait_engine.domain.models import PurchaseProposal


class TestPurchaseValidator(unittest.TestCase):
    def setUp(self):
        self.valid_payload = {
            "requested_amount": "500.00",
            "currency": "USD",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-15",
            "allows_partial_payment": True,
            "item_description": "Ergonomic Office Chair",
            "merchant_name": "Herman Miller",
            "category": "furniture",
        }

    def test_valid_payload_builds_proposal(self):
        proposal = PurchaseValidator.validate_and_build(
            self.valid_payload,
            user_id="user_123",
            request_id="req_001",
        )
        self.assertIsInstance(proposal, PurchaseProposal)
        self.assertEqual(proposal.requested_amount, Decimal("500.00"))
        self.assertEqual(proposal.currency, "USD")
        self.assertEqual(proposal.request_date, date(2026, 3, 1))
        self.assertEqual(proposal.desired_completion_date, date(2026, 3, 15))
        self.assertTrue(proposal.allows_partial_payment)
        self.assertEqual(proposal.item_description, "Ergonomic Office Chair")

    def test_missing_requested_amount(self):
        data = self.valid_payload.copy()
        del data["requested_amount"]
        with self.assertRaises(InvalidPurchaseError) as ctx:
            PurchaseValidator.validate_and_build(data, user_id="user_123")
        self.assertEqual(ctx.exception.field_name, "requested_amount")

    def test_negative_or_zero_amount(self):
        for bad_amt in ["0.00", "-100.50"]:
            data = self.valid_payload.copy()
            data["requested_amount"] = bad_amt
            with self.assertRaises(InvalidPurchaseError) as ctx:
                PurchaseValidator.validate_and_build(data, user_id="user_123")
            self.assertEqual(ctx.exception.field_name, "requested_amount")

    def test_invalid_currency_code(self):
        for bad_curr in ["US", "DOLLARS", "123", ""]:
            data = self.valid_payload.copy()
            data["currency"] = bad_curr
            with self.assertRaises(InvalidPurchaseError) as ctx:
                PurchaseValidator.validate_and_build(data, user_id="user_123")
            self.assertEqual(ctx.exception.field_name, "currency")

    def test_completion_date_earlier_than_request_date(self):
        data = self.valid_payload.copy()
        data["request_date"] = "2026-03-15"
        data["desired_completion_date"] = "2026-03-01"
        with self.assertRaises(InvalidPurchaseError) as ctx:
            PurchaseValidator.validate_and_build(data, user_id="user_123")
        self.assertEqual(ctx.exception.field_name, "desired_completion_date")

    def test_payment_options_parsing(self):
        data = self.valid_payload.copy()
        data["payment_options"] = [
            {
                "payment_option_id": "opt_full",
                "payment_type": "full_payment",
                "number_of_payments": 1,
                "installment_amount": "500.00",
                "total_amount": "500.00",
            },
            {
                "payment_option_id": "opt_3mo",
                "payment_type": "installment",
                "number_of_payments": 3,
                "installment_amount": "170.00",
                "total_amount": "510.00",
                "interest_rate_pct": "2.00",
                "payment_frequency_days": 30,
            }
        ]
        proposal = PurchaseValidator.validate_and_build(data, user_id="user_123")
        self.assertEqual(len(proposal.payment_options), 2)
        opt_3mo = proposal.payment_options[1]
        self.assertEqual(opt_3mo.number_of_payments, 3)
        self.assertEqual(opt_3mo.installment_amount, Decimal("170.00"))
        self.assertEqual(opt_3mo.total_amount, Decimal("510.00"))


if __name__ == "__main__":
    unittest.main()
