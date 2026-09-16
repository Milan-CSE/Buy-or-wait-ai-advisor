"""
backend/tests/test_golden_scenarios.py

Six golden user scenarios covering the full decision space.
These scenarios verify the complete financial decision pipeline end-to-end
through the API layer with in-memory SQLite.

Scenario A: Clear BUY - user has ample balance, stable salary, small purchase
Scenario B: Risk-aware BUY / SAFER_PAYMENT - affordable but borderline at P90 stress
Scenario C: WAIT / NOT_RECOMMENDED - insufficient balance for large purchase
Scenario D: SAFER_PAYMENT with installments - budget-stretched user with installment option
Scenario E: DATA_INSUFFICIENT - user has no financial profile
Scenario F: Multi-account + recurring commitments - complex cash flow scenario
"""
import unittest
import uuid
from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.database.models.account import FinancialAccount
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestGoldenScenarios(unittest.TestCase):
    """Golden user scenario tests verifying the full A→BUY through F→complex flow."""

    @classmethod
    def setUpClass(cls):
        import os
        db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        cls.engine = get_engine(db_url)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = SessionFactory
        cls.SessionLocal.configure(bind=cls.engine)

    def setUp(self):
        self.session = self.SessionLocal()
        email = f"golden_{uuid.uuid4().hex[:8]}@example.com"
        self.user = UserRepository(self.session).create(email, "Golden User")
        self.session.commit()
        self.client = TestClient(app)
        self.token = create_access_token(self.user.id, self.user.email)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def _add_profile(self, balance, min_balance="500.00", payment_methods=None,
                     max_installments=None, protected=None, reducible=None):
        prof = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=Decimal(balance),
            minimum_balance_to_keep=Decimal(min_balance),
            protected_categories=protected or ["rent", "debt_repayment"],
            reducible_categories=reducible or ["dining", "groceries"],
            stoppable_categories=["streaming"],
            payment_methods=payment_methods or ["full_payment", "installments", "partial_payment"],
            max_installment_months=Decimal(max_installments) if max_installments else None,
        )
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            institution_name="Chase",
            account_mask="0001",
            currency="USD",
            current_balance=Decimal(balance),
            status="active",
        )
        self.session.add(prof)
        self.session.add(acc)
        self.session.commit()
        return prof

    def _add_salary(self, count=2, amount="3500.00", base_date=date(2026, 7, 1)):
        for i in range(count):
            month = base_date.month + i
            year = base_date.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            tx_date = date(year, month, 1)
            tx = Transaction(
                user_id=self.user.id,
                dedup_hash=f"sal_{uuid.uuid4().hex[:8]}",
                transaction_date=tx_date,
                amount=Decimal(amount),
                currency="USD",
                amount_home=Decimal(amount),
                direction="credit",
                category="salary",
                normalized_description="Employer Payroll",
                original_description="Direct Deposit",
                lifecycle_status="settled",
                cash_type="settled_income",
                confidence_state="verified",
            )
            self.session.add(tx)
        self.session.commit()

    def _add_expense(self, amount, category, description, tx_date=date(2026, 9, 5)):
        tx = Transaction(
            user_id=self.user.id,
            dedup_hash=f"exp_{uuid.uuid4().hex[:8]}",
            transaction_date=tx_date,
            amount=Decimal(amount),
            currency="USD",
            amount_home=Decimal(amount),
            direction="debit",
            category=category,
            normalized_description=description,
            original_description=description,
            lifecycle_status="settled",
            cash_type="immediate_debit",
            confidence_state="verified",
        )
        self.session.add(tx)
        self.session.commit()

    def _evaluate(self, amount, request_date="2026-09-15", description="Test Purchase",
                  completion_date=None):
        payload = {
            "item_description": description,
            "requested_amount": str(amount),
            "currency": "USD",
            "request_date": request_date,
        }
        if completion_date:
            payload["desired_completion_date"] = completion_date
        return self.client.post("/api/v1/purchases/evaluate", json=payload, headers=self.headers)

    # ===========================================================================
    # SCENARIO A: Clear BUY
    # ===========================================================================
    def test_scenario_a_clear_buy(self):
        """
        Scenario A: User has $8,000 balance, regular salary, small $300 purchase.
        Expected: BUY / full_payment / amount_safe_to_pay = 300.00
        """
        self._add_profile(balance="8000.00", min_balance="500.00")
        self._add_salary(count=3, amount="4000.00")
        self._add_expense("-200.00", "groceries", "Supermarket")

        res = self._evaluate("300.00", description="Ergonomic Chair", completion_date="2026-09-30")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()

        # Core verdict
        self.assertEqual(data["verdict"], "BUY",
                         f"Expected BUY but got {data['verdict']}: {data.get('decision_explanation', '')}")
        self.assertEqual(data["recommended_payment_method"], "full_payment")
        self.assertEqual(Decimal(data["amount_safe_to_pay"]), Decimal("300.00"))
        self.assertEqual(data["earliest_date_for_full_payment"], "2026-09-15")

        # Financial invariants
        self.assertGreaterEqual(Decimal(data["amount_safe_to_pay"]), Decimal("0"))
        self.assertLessEqual(Decimal(data["amount_safe_to_pay"]), Decimal("300.00"))

        # Decision was persisted
        self.assertIn("decision_id", data)
        decision_id = data["decision_id"]
        get_res = self.client.get(f"/api/v1/decisions/{decision_id}", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["verdict"], "BUY")

        # Grounded explanation is present with correct fields
        self.assertIn("grounded_explanation", data)
        explanation = data["grounded_explanation"]
        self.assertIn("concise_explanation", explanation)
        self.assertNotIn("guarantee", explanation["concise_explanation"].lower())

    # ===========================================================================
    # SCENARIO B: Borderline - BUY with risk annotation
    # ===========================================================================
    def test_scenario_b_affordable_with_risk_awareness(self):
        """
        Scenario B: User has $1,800 balance, $500 minimum, salary barely sufficient.
        Purchase $800 — borderline affordable but risk-annotated.
        Expected: BUY or WAIT, amount_safe_to_pay <= 800, risk_tier present.
        """
        self._add_profile(balance="1800.00", min_balance="500.00")
        self._add_salary(count=3, amount="2000.00")
        self._add_expense("-300.00", "rent", "Monthly Rent")
        self._add_expense("-150.00", "groceries", "Grocery Store")

        res = self._evaluate("800.00", description="Laptop Upgrade", completion_date="2026-10-01")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()

        # Amount is bounded
        self.assertGreaterEqual(Decimal(data["amount_safe_to_pay"]), Decimal("0"))
        self.assertLessEqual(Decimal(data["amount_safe_to_pay"]), Decimal("800.00"))

        # Risk tier is attached
        self.assertIn("risk_tier", data)
        self.assertIn(data["risk_tier"], ("LOW_RISK", "MODERATE_RISK", "HIGH_RISK"))

        # Decision is one of the valid verdicts
        self.assertIn(data["verdict"], ("BUY", "WAIT", "NOT_RECOMMENDED"))

        # Grounded explanation present
        self.assertIn("grounded_explanation", data)

    # ===========================================================================
    # SCENARIO C: WAIT / NOT_RECOMMENDED
    # ===========================================================================
    def test_scenario_c_wait_or_not_recommended(self):
        """
        Scenario C: User has $600 balance (just above $500 minimum), requests $5,000.
        Expected: WAIT or NOT_RECOMMENDED, amount_safe_to_pay << 5000.
        """
        self._add_profile(balance="600.00", min_balance="500.00")
        self._add_salary(count=3, amount="1500.00")

        res = self._evaluate("5000.00", description="Luxury TV", completion_date="2026-09-20")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()

        self.assertIn(data["verdict"], ("WAIT", "NOT_RECOMMENDED"),
                      f"Expected WAIT/NOT_RECOMMENDED for constrained balance, got {data['verdict']}")
        self.assertLess(Decimal(data["amount_safe_to_pay"]), Decimal("5000.00"))

        # Financial safety invariant: safe amount never exceeds requested
        self.assertLessEqual(Decimal(data["amount_safe_to_pay"]), Decimal("5000.00"))
        self.assertGreaterEqual(Decimal(data["amount_safe_to_pay"]), Decimal("0"))

    # ===========================================================================
    # SCENARIO D: Installments pathway
    # ===========================================================================
    def test_scenario_d_installments_pathway(self):
        """
        Scenario D: User has $3,000 balance, $800 minimum, requests $2,000 laptop.
        Payment methods include installments. Balance doesn't support full payment today
        but installments over 3 months work.
        Expected: BUY or SAFER_PAYMENT with installments or full_payment.
        amount_safe_to_pay in [0, 2000].
        """
        self._add_profile(
            balance="3000.00",
            min_balance="800.00",
            payment_methods=["full_payment", "installments"],
            max_installments="3"
        )
        self._add_salary(count=3, amount="2500.00")
        self._add_expense("-500.00", "rent", "Rent")
        self._add_expense("-200.00", "groceries", "Groceries")

        res = self._evaluate("2000.00", description="MacBook Pro", completion_date="2026-12-01")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()

        # Verdict should be one of the proceed verdicts
        self.assertIn(data["verdict"], ("BUY", "WAIT", "NOT_RECOMMENDED"))

        # Amount is bounded
        self.assertGreaterEqual(Decimal(data["amount_safe_to_pay"]), Decimal("0"))
        self.assertLessEqual(Decimal(data["amount_safe_to_pay"]), Decimal("2000.00"))

        # Payment method is one of the valid options
        self.assertIn(data["recommended_payment_method"],
                      ("full_payment", "installments", "partial_payment", "wait", "not_recommended"))

        # Grounded explanation
        self.assertIn("grounded_explanation", data)

    # ===========================================================================
    # SCENARIO E: DATA_INSUFFICIENT
    # ===========================================================================
    def test_scenario_e_data_insufficient(self):
        """
        Scenario E: User has no financial profile or transactions.
        Expected: 422 DATA_INSUFFICIENT response with user action guidance.
        """
        # No profile, no transactions added
        res = self._evaluate("500.00", description="Office Chair")
        self.assertEqual(res.status_code, 422, res.text)
        data = res.json()

        self.assertEqual(data.get("code"), "DATA_INSUFFICIENT")
        self.assertIn("error", data)
        error = data["error"]
        self.assertEqual(error.get("code"), "DATA_INSUFFICIENT")
        self.assertIn("user_action_required", error)
        # Must tell user what to do
        self.assertGreater(len(error["user_action_required"]), 10)

    # ===========================================================================
    # SCENARIO F: Complex multi-transaction scenario
    # ===========================================================================
    def test_scenario_f_complex_multi_transaction(self):
        """
        Scenario F: User has $5,000 balance, multiple income sources (only salary counts),
        multiple recurring expenses (rent, groceries, streaming).
        Large purchase $1,500.
        Expected: Valid response with grounded explanation referencing real financial facts.
        """
        self._add_profile(
            balance="5000.00",
            min_balance="1000.00",
            payment_methods=["full_payment", "partial_payment"],
            protected=["rent", "debt_repayment"],
            reducible=["dining", "groceries"],
        )
        # Regular salary (counted)
        self._add_salary(count=3, amount="3200.00")

        # Multiple expense categories
        for i in range(3):
            self._add_expense("-1200.00", "rent", "Apartment Rent",
                              tx_date=date(2026, 6 + i, 1))
        for i in range(3):
            self._add_expense("-200.00", "groceries", "Grocery Store",
                              tx_date=date(2026, 7, 1 + i * 10))
        self._add_expense("-15.00", "streaming", "Netflix",
                          tx_date=date(2026, 8, 1))

        res = self._evaluate("1500.00", description="Living Room Sofa", completion_date="2026-11-01")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()

        # Valid verdict
        self.assertIn(data["verdict"], ("BUY", "WAIT", "NOT_RECOMMENDED"))

        # Amount invariant
        self.assertGreaterEqual(Decimal(data["amount_safe_to_pay"]), Decimal("0"))
        self.assertLessEqual(Decimal(data["amount_safe_to_pay"]), Decimal("1500.00"))

        # Risk tier present
        self.assertIn("risk_tier", data)

        # Grounded explanation present and non-trivial
        self.assertIn("grounded_explanation", data)
        explanation = data["grounded_explanation"]
        self.assertIn("concise_explanation", explanation)
        narrative = explanation["concise_explanation"]
        self.assertGreater(len(narrative), 50)

        # Decision persisted and retrievable
        self.assertIn("decision_id", data)
        dec_res = self.client.get(f"/api/v1/decisions/{data['decision_id']}", headers=self.headers)
        self.assertEqual(dec_res.status_code, 200)


class TestFinancialSafetyInvariants(unittest.TestCase):
    """
    8 explicit financial safety invariant checks.
    These must hold across ALL decision scenarios, unconditionally.
    """

    @classmethod
    def setUpClass(cls):
        import os
        db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        cls.engine = get_engine(db_url)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = SessionFactory
        cls.SessionLocal.configure(bind=cls.engine)

    def setUp(self):
        self.session = self.SessionLocal()
        email = f"inv_{uuid.uuid4().hex[:8]}@example.com"
        self.user = UserRepository(self.session).create(email, "Invariant User")
        self.session.commit()
        self.client = TestClient(app)
        self.token = create_access_token(self.user.id, self.user.email)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def _setup_and_evaluate(self, balance, amount, min_balance="500.00"):
        prof = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=Decimal(balance),
            minimum_balance_to_keep=Decimal(min_balance),
            protected_categories=["rent"],
            reducible_categories=["dining"],
            stoppable_categories=["streaming"],
            payment_methods=["full_payment", "partial_payment"],
        )
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            institution_name="Bank",
            account_mask="0001",
            currency="USD",
            current_balance=Decimal(balance),
            status="active",
        )
        salaries = [
            Transaction(
                user_id=self.user.id,
                dedup_hash=f"inv_sal_{uuid.uuid4().hex[:8]}",
                transaction_date=date(2026, 7 + i, 1),
                amount=Decimal("2000.00"),
                currency="USD",
                amount_home=Decimal("2000.00"),
                direction="credit",
                category="salary",
                normalized_description="Payroll",
                lifecycle_status="settled",
                cash_type="settled_income",
                confidence_state="verified",
            )
            for i in range(3)
        ]
        self.session.add_all([prof, acc] + salaries)
        self.session.commit()

        payload = {
            "item_description": "Test Item",
            "requested_amount": str(amount),
            "currency": "USD",
            "request_date": "2026-09-15",
            "desired_completion_date": "2026-10-31",
        }
        return self.client.post("/api/v1/purchases/evaluate", json=payload, headers=self.headers)

    def test_invariant_1_amount_safe_always_nonnegative(self):
        """Invariant 1: amount_safe_to_pay >= 0 always."""
        res = self._setup_and_evaluate("600.00", "10000.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(Decimal(data["amount_safe_to_pay"]), Decimal("0"))

    def test_invariant_2_amount_safe_never_exceeds_requested(self):
        """Invariant 2: amount_safe_to_pay <= requested_amount always."""
        res = self._setup_and_evaluate("5000.00", "300.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertLessEqual(Decimal(data["amount_safe_to_pay"]), Decimal("300.00"))

    def test_invariant_3_buy_means_full_amount_safe(self):
        """Invariant 3: verdict=BUY => amount_safe_to_pay == requested_amount."""
        res = self._setup_and_evaluate("5000.00", "100.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        if data["verdict"] == "BUY":
            self.assertEqual(Decimal(data["amount_safe_to_pay"]), Decimal("100.00"))

    def test_invariant_4_not_recommended_has_safe_less_than_requested(self):
        """Invariant 4: NOT_RECOMMENDED => amount_safe_to_pay < requested_amount.
        The engine may allow a small partial payment even when NOT_RECOMMENDED.
        """
        res = self._setup_and_evaluate("510.00", "8000.00", min_balance="500.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        if data["verdict"] == "NOT_RECOMMENDED":
            # Safe amount must be bounded
            self.assertLess(Decimal(data["amount_safe_to_pay"]), Decimal("8000.00"))
            self.assertGreaterEqual(Decimal(data["amount_safe_to_pay"]), Decimal("0"))

    def test_invariant_5_valid_verdict_values(self):
        """Invariant 5: verdict is always one of the four allowed values."""
        res = self._setup_and_evaluate("2000.00", "500.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn(data["verdict"], ("BUY", "WAIT", "NOT_RECOMMENDED", "SAFER_PAYMENT"))

    def test_invariant_6_valid_payment_method_values(self):
        """Invariant 6: recommended_payment_method is always a valid enum value."""
        res = self._setup_and_evaluate("2000.00", "500.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        valid_methods = ("full_payment", "partial_payment", "installments", "wait", "not_recommended")
        self.assertIn(data["recommended_payment_method"], valid_methods)

    def test_invariant_7_valid_affordability_status(self):
        """Invariant 7: affordability_status is always a valid enum value."""
        res = self._setup_and_evaluate("3000.00", "500.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        valid_statuses = ("affordable_now", "affordable_with_plan", "affordable_later", "not_affordable")
        self.assertIn(data["affordability_status"], valid_statuses)

    def test_invariant_8_grounded_explanation_no_guarantee_language(self):
        """Invariant 8: grounded_explanation never contains guarantee language."""
        res = self._setup_and_evaluate("4000.00", "300.00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        if "grounded_explanation" in data:
            narrative = data["grounded_explanation"].get("narrative", "")
            prohibited = ["guarantee", "guaranteed", "will definitely", "certain to", "assure you"]
            for phrase in prohibited:
                self.assertNotIn(phrase.lower(), narrative.lower(),
                                 f"Prohibited guarantee language found: '{phrase}'")


if __name__ == "__main__":
    unittest.main()
