from backend.auth.jwt import create_access_token
"""
backend/tests/test_api/test_accounts_api.py
"""
from decimal import Decimal
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.database.repositories import AccountRepository, UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestAccountsAPI(unittest.TestCase):
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
        self.user = UserRepository(self.session).create(f"acc_{uuid.uuid4().hex[:6]}@example.com", "Account User")
        self.session.commit()
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user.id, self.user.email)}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_list_and_get_account(self):
        acc_repo = AccountRepository(self.session, self.user.id)
        acc1 = acc_repo.create("checking", "Chase", "1111", "USD", Decimal("1200.00"))
        acc2 = acc_repo.create("savings", "Ally", "2222", "USD", Decimal("3500.00"))
        self.session.commit()

        # List accounts
        res = self.client.get("/api/v1/accounts", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)

        # Get specific account
        get_res = self.client.get(f"/api/v1/accounts/{acc1.id}", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["institution_name"], "Chase")
        self.assertEqual(Decimal(get_res.json()["current_balance"]), Decimal("1200.00"))


if __name__ == "__main__":
    unittest.main()
