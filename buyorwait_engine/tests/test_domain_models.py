"""
Tests for domain model validation, Decimal enforcement, and immutability.
"""
import unittest
from datetime import date
from decimal import Decimal

from buyorwait_engine.domain.models import (
    PurchaseProposal,
    FinancialProfileInput,
    CashflowEventInput,
    PaymentOptionInput,
    DecisionResult,
)
from buyorwait_engine.domain.enums import Verdict, AffordabilityStatus, PaymentMethod


class TestDomainModels(unittest.TestCase):
    def test_float_rejected_for_proposal_amount(self):
        with self.assertRaises(TypeError) as ctx:
            PurchaseProposal(
                request_id="req_01",
                user_id="user_01",
                requested_amount=150.50,  # float, not Decimal
                currency="USD",
                request_date=date(2026, 9, 15),
                desired_completion_date=date(2026, 9, 30),
                item_category="electronics",
            )
        self.assertIn("must be Decimal", str(ctx.exception))

    def test_negative_proposal_amount_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            PurchaseProposal(
                request_id="req_01",
                user_id="user_01",
                requested_amount=Decimal("-10.00"),
                currency="USD",
                request_date=date(2026, 9, 15),
                desired_completion_date=date(2026, 9, 30),
                item_category="electronics",
            )
        self.assertIn("must be strictly positive", str(ctx.exception))

    def test_invalid_date_ordering_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            PurchaseProposal(
                request_id="req_01",
                user_id="user_01",
                requested_amount=Decimal("100.00"),
                currency="USD",
                request_date=date(2026, 9, 30),
                desired_completion_date=date(2026, 9, 15),  # before request_date
                item_category="electronics",
            )
        self.assertIn("cannot be earlier than request_date", str(ctx.exception))

    def test_valid_proposal(self):
        prop = PurchaseProposal(
            request_id="req_01",
            user_id="user_01",
            requested_amount=Decimal("100.00"),
            currency="USD",
            request_date=date(2026, 9, 15),
            desired_completion_date=date(2026, 9, 30),
            item_category="electronics",
        )
        self.assertEqual(prop.requested_amount, Decimal("100.00"))

    def test_profile_immutability(self):
        prof = FinancialProfileInput(
            user_id="user_01",
            home_currency="USD",
            current_available_balance=Decimal("1000.00"),
            minimum_balance_to_keep=Decimal("200.00"),
            financial_priorities=("savings",),
            protected_categories=("groceries",),
            reducible_categories=("dining",),
            stoppable_categories=("streaming",),
            payment_methods=("credit_card",),
            max_installment_months=Decimal("6"),
        )
        with self.assertRaises(AttributeError):
            prof.current_available_balance = Decimal("2000.00")


if __name__ == '__main__':
    unittest.main()
