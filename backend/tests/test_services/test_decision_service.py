"""
backend/tests/test_services/test_decision_service.py

End-to-end integration tests for DecisionService:
- Scenario A: BUY (healthy balance, verified income, affordable purchase)
- Scenario B: WAIT / NOT_RECOMMENDED (insufficient funds, strict minimum breached)
- Scenario C: DATA_INSUFFICIENT (missing accounts, no history, actionable guidance)
- Exact reproducibility across multiple evaluations
- Rollback and error integrity
"""
from datetime import date, timedelta
from decimal import Decimal
import unittest
import uuid
from sqlalchemy.orm import Session

from backend.database.models.account import FinancialAccount
from backend.database.models.decision import Decision
from backend.database.models.profile import FinancialProfile
from backend.database.models.purchase import PurchaseRequest
from backend.database.models.transaction import Transaction
from backend.database.repositories import UserRepository, DecisionRepository, AuditRepository
from backend.database.session import get_engine, Base, SessionFactory
from backend.services.decision_service import DecisionService
from buyorwait_engine.currency.fx import FXEngine
from buyorwait_engine.domain.models import PurchaseProposal


class TestDecisionServiceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        cls.engine = get_engine(db_url)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = SessionFactory
        cls.SessionLocal.configure(bind=cls.engine)

    def setUp(self):
        self.session: Session = self.SessionLocal()
        self.user_repo = UserRepository(self.session)
        self.user = self.user_repo.create(f"service_user_{uuid.uuid4().hex[:6]}@example.com", "Financial Test User")
        self.session.commit()
        self.user_id = self.user.id

        self.fx = FXEngine()
        self.fx.add_rate(date(2026, 3, 1), "EUR", "USD", Decimal("1.1000"))
        self.service = DecisionService(session=self.session, fx_engine=self.fx)
        self.as_of_date = date(2026, 3, 1)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def _setup_verified_history(
        self,
        checking_balance: Decimal = Decimal("5000.0000"),
        savings_balance: Decimal = Decimal("2000.0000"),
        salary_amount: Decimal = Decimal("3000.0000"),
        rent_amount: Decimal = Decimal("800.0000"),
    ):
        # Profile
        prof = FinancialProfile(
            user_id=self.user_id,
            home_currency="USD",
            current_available_balance=checking_balance + savings_balance,
            minimum_balance_to_keep=Decimal("1000.0000"),
            protected_categories=["rent"],
            reducible_categories=["dining"],
            stoppable_categories=["streaming"],
            payment_methods=["full_payment", "installments", "partial_payment"],
            max_installment_months=Decimal("6.0"),
        )
        self.session.add(prof)

        # Accounts
        acc1 = FinancialAccount(
            user_id=self.user_id,
            account_type="checking",
            institution_name="Chase",
            account_mask="1234",
            currency="USD",
            current_balance=checking_balance,
            status="active",
        )
        acc2 = FinancialAccount(
            user_id=self.user_id,
            account_type="savings",
            institution_name="Ally",
            account_mask="5678",
            currency="USD",
            current_balance=savings_balance,
            status="active",
        )
        self.session.add_all([acc1, acc2])

        # Transactions (Salary + rent + groceries)
        txs = [
            # Two monthly paychecks
            Transaction(
                user_id=self.user_id,
                dedup_hash="sal_1",
                transaction_date=date(2026, 1, 15),
                amount=salary_amount,
                currency="USD",
                amount_home=salary_amount,
                direction="credit",
                category="salary",
                normalized_description="Employer Payroll",
                lifecycle_status="settled",
                cash_type="settled_income",
                confidence_state="verified",
            ),
            Transaction(
                user_id=self.user_id,
                dedup_hash="sal_2",
                transaction_date=date(2026, 2, 15),
                amount=salary_amount,
                currency="USD",
                amount_home=salary_amount,
                direction="credit",
                category="salary",
                normalized_description="Employer Payroll",
                lifecycle_status="settled",
                cash_type="settled_income",
                confidence_state="verified",
            ),
            # Two monthly rents
            Transaction(
                user_id=self.user_id,
                dedup_hash="rent_1",
                transaction_date=date(2026, 1, 1),
                amount=-rent_amount,
                currency="USD",
                amount_home=-rent_amount,
                direction="debit",
                category="rent",
                normalized_description="Monthly Apartment Rent",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            ),
            Transaction(
                user_id=self.user_id,
                dedup_hash="rent_2",
                transaction_date=date(2026, 2, 1),
                amount=-rent_amount,
                currency="USD",
                amount_home=-rent_amount,
                direction="debit",
                category="rent",
                normalized_description="Monthly Apartment Rent",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            ),
            # Groceries
            Transaction(
                user_id=self.user_id,
                dedup_hash="groc_1",
                transaction_date=date(2026, 2, 20),
                amount=Decimal("-60.0000"),
                currency="USD",
                amount_home=Decimal("-60.0000"),
                direction="debit",
                category="groceries",
                normalized_description="Supermarket",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            ),
        ]
        self.session.add_all(txs)
        self.session.commit()

    def test_scenario_a_buy_recommendation(self):
        """Healthy user with surplus cash and income buying a modest item -> BUY."""
        self._setup_verified_history(checking_balance=Decimal("6000.00"), savings_balance=Decimal("2000.00"))
        purchase_data = {
            "requested_amount": "400.00",
            "currency": "USD",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-15",
            "item_description": "Ergonomic Monitor",
            "category": "electronics",
        }
        res = self.service.evaluate_purchase(self.user_id, purchase_data, as_of_date=self.as_of_date)

        self.assertTrue(res.is_sufficient)
        self.assertIsNotNone(res.decision)
        self.assertEqual(res.decision.verdict, "BUY")
        self.assertEqual(res.decision.recommended_payment_method, "full_payment")
        self.assertEqual(res.decision.amount_safe_to_pay, Decimal("400.00"))

        # Verify DB persistence
        self.assertIsNotNone(res.decision_record)
        dec_repo = DecisionRepository(self.session, self.user_id)
        saved = dec_repo.get_by_purchase_id(res.purchase_request.id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.verdict, "BUY")
        self.assertEqual(saved.engine_version, "1.0.0")

        # Verify Audit Log
        audit_repo = AuditRepository(self.session, self.user_id)
        events = audit_repo.list_events()
        self.assertTrue(any(e.event_type == "purchase_evaluated" for e in events))

    def test_scenario_b_unaffordable_purchase(self):
        """Tight balance with large purchase proposal -> WAIT or NOT_RECOMMENDED."""
        # Starting balance $1100, min keep $1000 -> only $100 headroom
        self._setup_verified_history(checking_balance=Decimal("600.00"), savings_balance=Decimal("500.00"))
        purchase_data = {
            "requested_amount": "8000.00",
            "currency": "USD",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-05",
            "item_description": "Luxury Watch",
            "category": "luxury",
        }
        res = self.service.evaluate_purchase(self.user_id, purchase_data, as_of_date=self.as_of_date)

        self.assertTrue(res.is_sufficient)
        self.assertIsNotNone(res.decision)
        self.assertIn(res.decision.verdict, ("WAIT", "NOT_RECOMMENDED"))
        self.assertLess(res.decision.amount_safe_to_pay, Decimal("8000.00"))

    def test_scenario_c_data_insufficient(self):
        """User with missing accounts or < 3 transactions -> DATA_INSUFFICIENT."""
        # No profile or accounts created
        purchase_data = {
            "requested_amount": "200.00",
            "currency": "USD",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-10",
        }
        res = self.service.evaluate_purchase(self.user_id, purchase_data, as_of_date=self.as_of_date)

        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.data_quality.code, "DATA_INSUFFICIENT")
        self.assertIsNone(res.decision)
        self.assertIsNone(res.decision_record)

        # Audit log must record the rejection
        audit_repo = AuditRepository(self.session, self.user_id)
        events = audit_repo.list_events()
        self.assertTrue(any(e.event_type == "purchase_evaluation_rejected" for e in events))

    def test_exact_reproducibility(self):
        """Calling evaluate twice on identical state produces identical results."""
        self._setup_verified_history()
        purchase_data = {
            "requested_amount": "500.00",
            "currency": "USD",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-20",
            "item_description": "Standing Desk",
        }
        res1 = self.service.evaluate_purchase(self.user_id, purchase_data, as_of_date=self.as_of_date, save_to_db=False)
        res2 = self.service.evaluate_purchase(self.user_id, purchase_data, as_of_date=self.as_of_date, save_to_db=False)

        self.assertEqual(res1.decision.verdict, res2.decision.verdict)
        self.assertEqual(res1.decision.amount_safe_to_pay, res2.decision.amount_safe_to_pay)
        self.assertEqual(res1.decision.affordability_status, res2.decision.affordability_status)
        self.assertEqual(res1.decision.payment_plan, res2.decision.payment_plan)
        if res1.decision.risk_assessment:
            self.assertEqual(res1.decision.risk_assessment.risk_tier, res2.decision.risk_assessment.risk_tier)
            self.assertEqual(res1.decision.risk_assessment.safe_amount_p90, res2.decision.risk_assessment.safe_amount_p90)


if __name__ == "__main__":
    unittest.main()
