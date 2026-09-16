from backend.auth.jwt import create_access_token
"""
backend/tests/test_api/test_transactions_api.py
"""
from datetime import date
from decimal import Decimal
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.database.models.transaction import Transaction
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestTransactionsAPI(unittest.TestCase):
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
        self.user = UserRepository(self.session).create(f"tx_user_{uuid.uuid4().hex[:6]}@example.com", "Tx User")
        self.session.commit()
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user.id, self.user.email)}"}

        # Seed 5 transactions across dates and categories
        txs = [
            Transaction(
                user_id=self.user.id,
                dedup_hash=f"hash_{i}",
                transaction_date=date(2026, 2, i + 1),
                amount=Decimal(f"-{10 * (i + 1)}.00"),
                currency="USD",
                amount_home=Decimal(f"-{10 * (i + 1)}.00"),
                direction="debit",
                category="groceries" if i % 2 == 0 else "dining",
                normalized_description=f"Store {i}",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            )
            for i in range(5)
        ]
        self.session.add_all(txs)
        self.session.commit()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_list_transactions_with_pagination(self):
        res = self.client.get("/api/v1/transactions?page=1&page_size=3", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 5)
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["total_pages"], 2)

    def test_filter_by_category(self):
        res = self.client.get("/api/v1/transactions?category=groceries", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 3)
        self.assertTrue(all(it["category"] == "groceries" for it in data["items"]))

    def test_filter_by_date_range(self):
        res = self.client.get("/api/v1/transactions?start_date=2026-02-02&end_date=2026-02-04", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 3)


if __name__ == "__main__":
    unittest.main()
