from backend.auth.jwt import create_access_token
"""
backend/tests/test_api/test_idempotency_api.py
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


class TestIdempotencyAPI(unittest.TestCase):
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
        self.user = UserRepository(self.session).create(f"idem_{uuid.uuid4().hex[:6]}@example.com", "Idem User")
        self.session.commit()

        # Healthy state
        prof = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=Decimal("5000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
        )
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            institution_name="Bank",
            account_mask="1234",
            currency="USD",
            current_balance=Decimal("5000.00"),
            status="active",
        )
        txs = [
            Transaction(
                user_id=self.user.id,
                dedup_hash=f"tx_hash_{i}",
                transaction_date=date(2026, 1, 10 + i * 5),
                amount=Decimal("2000.00" if i == 0 else "-50.00"),
                currency="USD",
                amount_home=Decimal("2000.00" if i == 0 else "-50.00"),
                direction="credit" if i == 0 else "debit",
                category="salary" if i == 0 else "groceries",
                normalized_description="Desc",
                lifecycle_status="settled",
                cash_type="settled_income" if i == 0 else "immediate_debit",
                confidence_state="verified",
            )
            for i in range(3)
        ]
        self.session.add_all([prof, acc] + txs)
        self.session.commit()

        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user.id, self.user.email)}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_idempotent_replay(self):
        key = "eval_key_12345"
        payload = {
            "item_description": "Office Desk",
            "requested_amount": "300.00",
            "currency": "USD",
            "request_date": "2026-03-01",
        }
        headers = {**self.headers, "X-Idempotency-Key": key}

        # First request -> fresh evaluation
        res1 = self.client.post("/api/v1/purchases/evaluate", json=payload, headers=headers)
        self.assertEqual(res1.status_code, 200)
        dec_id1 = res1.json()["decision_id"]

        # Second request with same key & payload -> cached replay
        res2 = self.client.post("/api/v1/purchases/evaluate", json=payload, headers=headers)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.headers.get("x-cache"), "HIT")
        self.assertEqual(res2.json()["decision_id"], dec_id1)

    def test_conflicting_idempotency_payload(self):
        key = "conflict_key_999"
        payload1 = {
            "item_description": "Item 1",
            "requested_amount": "100.00",
            "currency": "USD",
            "request_date": "2026-03-01",
        }
        headers = {**self.headers, "X-Idempotency-Key": key}
        res1 = self.client.post("/api/v1/purchases/evaluate", json=payload1, headers=headers)
        self.assertEqual(res1.status_code, 200)

        # Different payload with same idempotency key -> 409 Conflict
        payload2 = {
            "item_description": "Item 2 (Different!)",
            "requested_amount": "500.00",
            "currency": "USD",
            "request_date": "2026-03-01",
        }
        res2 = self.client.post("/api/v1/purchases/evaluate", json=payload2, headers=headers)
        self.assertEqual(res2.status_code, 409)
        self.assertIn("conflicting request payload", res2.json()["detail"])


if __name__ == "__main__":
    unittest.main()
