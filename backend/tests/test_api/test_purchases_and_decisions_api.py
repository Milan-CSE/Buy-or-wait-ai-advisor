from backend.auth.jwt import create_access_token
"""
backend/tests/test_api/test_purchases_and_decisions_api.py
"""
from datetime import date
from decimal import Decimal
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.database.models.account import FinancialAccount
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestPurchasesAndDecisionsAPI(unittest.TestCase):
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
        self.user = UserRepository(self.session).create(f"purch_user_{uuid.uuid4().hex[:6]}@example.com", "Purch User")
        self.session.commit()
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user.id, self.user.email)}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def _setup_financial_state(self, balance: Decimal = Decimal("5000.00")):
        prof = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=balance,
            minimum_balance_to_keep=Decimal("1000.00"),
            protected_categories=["rent"],
            reducible_categories=["dining"],
            stoppable_categories=["streaming"],
            payment_methods=["full_payment", "installments", "partial_payment"],
            max_installment_months=Decimal("6.0"),
        )
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            institution_name="Bank",
            account_mask="1234",
            currency="USD",
            current_balance=balance,
            status="active",
        )
        txs = [
            Transaction(
                user_id=self.user.id,
                dedup_hash=f"hash_sal_{i}",
                transaction_date=date(2026, 1, 15 + i * 15),
                amount=Decimal("3000.00"),
                currency="USD",
                amount_home=Decimal("3000.00"),
                direction="credit",
                category="salary",
                normalized_description="Employer Payroll",
                lifecycle_status="settled",
                cash_type="settled_income",
                confidence_state="verified",
            )
            for i in range(2)
        ] + [
            Transaction(
                user_id=self.user.id,
                dedup_hash=f"hash_exp_{i}",
                transaction_date=date(2026, 1, 20 + i * 5),
                amount=Decimal("-100.00"),
                currency="USD",
                amount_home=Decimal("-100.00"),
                direction="debit",
                category="groceries",
                normalized_description="Market",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            )
            for i in range(2)
        ]
        self.session.add(prof)
        self.session.add(acc)
        self.session.add_all(txs)
        self.session.commit()

    def test_scenario_a_buy_decision(self):
        self._setup_financial_state(balance=Decimal("6000.00"))
        payload = {
            "item_description": "Ergonomic Monitor",
            "requested_amount": "400.00",
            "currency": "USD",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-15",
            "category": "electronics",
        }
        res = self.client.post("/api/v1/purchases/evaluate", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["verdict"], "BUY")
        self.assertEqual(data["recommended_payment_method"], "full_payment")
        self.assertEqual(Decimal(data["amount_safe_to_pay"]), Decimal("400.00"))
        self.assertIn("decision_id", data)

        decision_id = data["decision_id"]

        # Check Decision retrieval
        get_res = self.client.get(f"/api/v1/decisions/{decision_id}", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["verdict"], "BUY")

        # Check Decision history list
        list_res = self.client.get("/api/v1/decisions", headers=self.headers)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.json()["total"], 1)

    def test_scenario_b_wait_or_not_recommended(self):
        # Barely above minimum balance
        self._setup_financial_state(balance=Decimal("1050.00"))
        payload = {
            "item_description": "Luxury Watch",
            "requested_amount": "5000.00",
            "currency": "USD",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-05",
        }
        res = self.client.post("/api/v1/purchases/evaluate", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn(data["verdict"], ("WAIT", "NOT_RECOMMENDED"))
        self.assertLess(Decimal(data["amount_safe_to_pay"]), Decimal("5000.00"))

    def test_scenario_c_data_insufficient(self):
        # Empty user without profile or transactions
        payload = {
            "item_description": "Office Desk",
            "requested_amount": "300.00",
            "currency": "USD",
            "request_date": "2026-03-01",
        }
        res = self.client.post("/api/v1/purchases/evaluate", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 422)
        data = res.json()
        self.assertEqual(data["code"], "DATA_INSUFFICIENT")
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], "DATA_INSUFFICIENT")
        self.assertIn("user_action_required", data["error"])

    def test_invalid_purchase_payload(self):
        # Non-positive amount
        bad_payload = {
            "item_description": "Desk",
            "requested_amount": "-50.00",
            "currency": "USD",
            "request_date": "2026-03-01",
        }
        res = self.client.post("/api/v1/purchases/evaluate", json=bad_payload, headers=self.headers)
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
