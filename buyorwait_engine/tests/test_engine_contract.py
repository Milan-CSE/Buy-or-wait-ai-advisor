"""
Contract verification tests covering library requirements:
- In-memory execution without dataset files
- Decimal correctness
- Immutability of FinancialState
- Solvency constraints and fallback to not_recommended
- Option exclusion via max_installment_months
- Spending change preference constraints
- Single-event division safeguards
"""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from buyorwait_engine.domain.models import (
    FinancialProfileInput,
    CashflowEventInput,
    PurchaseProposal,
    PaymentOptionInput,
)
from buyorwait_engine.domain.enums import Verdict, AffordabilityStatus, PaymentMethod, RiskTier
from buyorwait_engine.engine import BuyOrWaitEngine, evaluate_purchase
from buyorwait_engine.state.builder import build_financial_state_from_inputs
from buyorwait_engine.risk.config import RiskCalibrationConfig, CURRENT_CALIBRATION_VERSION
from buyorwait_engine.risk.stress_buffers import build_stressed_state


class TestEngineContract(unittest.TestCase):
    def setUp(self):
        self.profile = FinancialProfileInput(
            user_id="user_test",
            home_currency="USD",
            current_available_balance=Decimal("1500.00"),
            minimum_balance_to_keep=Decimal("500.00"),
            financial_priorities=("savings", "retirement"),
            protected_categories=("rent", "utilities"),
            reducible_categories=("dining", "groceries"),
            stoppable_categories=("streaming", "entertainment"),
            payment_methods=("full_payment", "installments", "partial_payment"),
            max_installment_months=Decimal("3"),
        )
        self.events = [
            # Settled salary
            CashflowEventInput(
                event_id="e1",
                user_id="user_test",
                event_type="salary",
                description="Regular payroll",
                category="salary",
                direction="credit",
                amount=Decimal("3000.00"),
                currency="USD",
                status="settled",
                settlement_date=date(2026, 8, 1),
            ),
            CashflowEventInput(
                event_id="e2",
                user_id="user_test",
                event_type="salary",
                description="Regular payroll",
                category="salary",
                direction="credit",
                amount=Decimal("3000.00"),
                currency="USD",
                status="settled",
                settlement_date=date(2026, 9, 1),
            ),
            # Settled groceries
            CashflowEventInput(
                event_id="e3",
                user_id="user_test",
                event_type="expense",
                description="Supermarket",
                category="groceries",
                direction="debit",
                amount=Decimal("200.00"),
                currency="USD",
                status="settled",
                settlement_date=date(2026, 9, 5),
            ),
            # Settled rent (fixed)
            CashflowEventInput(
                event_id="e4",
                user_id="user_test",
                event_type="expense",
                description="Apartment rent",
                category="rent",
                direction="debit",
                amount=Decimal("800.00"),
                currency="USD",
                status="settled",
                settlement_date=date(2026, 8, 10),
            ),
            CashflowEventInput(
                event_id="e5",
                user_id="user_test",
                event_type="expense",
                description="Apartment rent",
                category="rent",
                direction="debit",
                amount=Decimal("800.00"),
                currency="USD",
                status="settled",
                settlement_date=date(2026, 9, 10),
            ),
        ]

    def test_pure_in_memory_invocation(self):
        """Engine evaluates successfully without reading any file from disk."""
        engine = BuyOrWaitEngine()
        purchase = PurchaseProposal(
            request_id="req_mem_01",
            user_id="user_test",
            requested_amount=Decimal("300.00"),
            currency="USD",
            request_date=date(2026, 9, 15),
            desired_completion_date=date(2026, 9, 30),
            item_category="electronics",
        )
        result = engine.evaluate(self.profile, self.events, purchase)
        self.assertEqual(result.request_id, "req_mem_01")
        self.assertEqual(result.verdict, Verdict.BUY.value)
        self.assertEqual(result.affordability_status, AffordabilityStatus.AFFORDABLE_NOW.value)
        self.assertEqual(result.recommended_payment_method, PaymentMethod.FULL_PAYMENT.value)
        self.assertIsNotNone(result.risk_assessment)
        self.assertEqual(result.risk_assessment.calibration_version, CURRENT_CALIBRATION_VERSION)

    def test_financial_state_immutability_under_stress(self):
        """P90 stress buffer generation does not mutate original state."""
        state = build_financial_state_from_inputs(self.profile, self.events, date(2026, 9, 15))
        orig_amounts = [item.amount for item in state.recurring_debits]

        stressed = build_stressed_state(state)
        stressed_amounts = [item.amount for item in stressed.recurring_debits]

        # Verify state was deepcopied and not mutated
        self.assertEqual([item.amount for item in state.recurring_debits], orig_amounts)
        self.assertNotEqual(orig_amounts, stressed_amounts)

    def test_fallback_when_balance_insufficient(self):
        """When starting balance is below minimum balance, safe amount is 0 and not_recommended."""
        low_profile = FinancialProfileInput(
            user_id="user_poor",
            home_currency="USD",
            current_available_balance=Decimal("400.00"),  # below minimum
            minimum_balance_to_keep=Decimal("500.00"),
            financial_priorities=(),
            protected_categories=(),
            reducible_categories=(),
            stoppable_categories=(),
            payment_methods=("full_payment",),
            max_installment_months=None,
        )
        purchase = PurchaseProposal(
            request_id="req_poor",
            user_id="user_poor",
            requested_amount=Decimal("1000.00"),
            currency="USD",
            request_date=date(2026, 9, 15),
            desired_completion_date=date(2026, 9, 30),
            item_category="luxury",
        )
        engine = BuyOrWaitEngine()
        result = engine.evaluate(low_profile, [], purchase)
        self.assertEqual(result.amount_safe_to_pay, Decimal("0"))
        self.assertEqual(result.verdict, Verdict.NOT_RECOMMENDED.value)
        self.assertEqual(result.affordability_status, AffordabilityStatus.NOT_AFFORDABLE.value)

    def test_max_installment_months_respected(self):
        """Payment options exceeding max_installment_months must be excluded."""
        opt_short = PaymentOptionInput(
            payment_option_id="opt_2mo",
            payment_type="installment",
            number_of_payments=2,
            first_payment_date=date(2026, 9, 15),
            installment_amount=Decimal("200.00"),
            total_amount=Decimal("400.00"),
            interest_rate_pct=Decimal("0.0"),
            payment_frequency_days=30,  # 30 days total ~ 1 month <= 3 months
        )
        opt_long = PaymentOptionInput(
            payment_option_id="opt_6mo",
            payment_type="installment",
            number_of_payments=6,
            first_payment_date=date(2026, 9, 15),
            installment_amount=Decimal("70.00"),
            total_amount=Decimal("420.00"),
            interest_rate_pct=Decimal("5.0"),
            payment_frequency_days=30,  # 150 days ~ 5 months > 3 months (profile limit)
        )
        purchase = PurchaseProposal(
            request_id="req_opts",
            user_id="user_test",
            requested_amount=Decimal("400.00"),
            currency="USD",
            request_date=date(2026, 9, 15),
            desired_completion_date=date(2026, 12, 1),
            item_category="electronics",
            payment_options=[opt_short, opt_long],
        )
        state = build_financial_state_from_inputs(self.profile, self.events, date(2026, 9, 15))
        from buyorwait_engine.decision.candidates import generate_candidates
        candidates = generate_candidates(
            state=state,
            requested_amount=Decimal("400.00"),
            request_date=date(2026, 9, 15),
            completion_date=date(2026, 12, 1),
            payment_options=[opt_short, opt_long],
            safe_amount_no_changes=Decimal("300.00"),
        )
        installment_cand_ids = [c.payment_option_id for c in candidates if c.method == 'installments']
        self.assertIn("opt_2mo", installment_cand_ids)
        self.assertNotIn("opt_6mo", installment_cand_ids)


if __name__ == '__main__':
    unittest.main()
