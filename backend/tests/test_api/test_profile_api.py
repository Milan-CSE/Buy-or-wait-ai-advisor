from backend.auth.jwt import create_access_token
"""
backend/tests/test_api/test_profile_api.py
"""
from decimal import Decimal
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestProfileAPI(unittest.TestCase):
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
        self.user = UserRepository(self.session).create(f"prof_{uuid.uuid4().hex[:6]}@example.com", "Profile User")
        self.session.commit()
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user.id, self.user.email)}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_profile_create_and_read(self):
        # 1. Update/create profile
        payload = {
            "home_currency": "USD",
            "current_available_balance": "4500.00",
            "minimum_balance_to_keep": "800.00",
            "protected_categories": ["rent", "utilities"],
            "reducible_categories": ["groceries", "dining"],
            "stoppable_categories": ["streaming"],
            "payment_methods": ["full_payment", "installments"],
            "max_installment_months": 6.0,
        }
        put_res = self.client.put("/api/v1/profile", json=payload, headers=self.headers)
        self.assertEqual(put_res.status_code, 200)
        data = put_res.json()
        self.assertEqual(data["home_currency"], "USD")
        self.assertEqual(Decimal(data["current_available_balance"]), Decimal("4500.00"))
        self.assertEqual(Decimal(data["minimum_balance_to_keep"]), Decimal("800.00"))
        self.assertEqual(data["profile_version"], 1)

        # 2. Read profile
        get_res = self.client.get("/api/v1/profile", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["current_available_balance"], "4500.0000")

        # 3. Update again -> increment version
        update_payload = {"current_available_balance": "5000.00"}
        put_res2 = self.client.put("/api/v1/profile", json=update_payload, headers=self.headers)
        self.assertEqual(put_res2.status_code, 200)
        self.assertEqual(put_res2.json()["profile_version"], 2)
        self.assertEqual(Decimal(put_res2.json()["current_available_balance"]), Decimal("5000.00"))


if __name__ == "__main__":
    unittest.main()
