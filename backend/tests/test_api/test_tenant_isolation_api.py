from backend.auth.jwt import create_access_token
"""
backend/tests/test_api/test_tenant_isolation_api.py
"""
from decimal import Decimal
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.database.models.account import FinancialAccount
from backend.database.models.decision import Decision
from backend.database.models.profile import FinancialProfile
from backend.database.models.purchase import PurchaseRequest
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestTenantIsolationAPI(unittest.TestCase):
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
        user_repo = UserRepository(self.session)
        self.user_a = user_repo.create(f"usera_{uuid.uuid4().hex[:6]}@example.com", "User A")
        self.user_b = user_repo.create(f"userb_{uuid.uuid4().hex[:6]}@example.com", "User B")
        self.session.commit()

        # Seed resources for User B
        self.acc_b = FinancialAccount(
            user_id=self.user_b.id,
            account_type="checking",
            institution_name="Bank B",
            account_mask="9999",
            currency="USD",
            current_balance=Decimal("1000.00"),
            status="active",
        )
        self.purch_b = PurchaseRequest(
            user_id=self.user_b.id,
            requested_amount=Decimal("100.00"),
            currency="USD",
            request_date=Decimal("100.00"),
            desired_completion_date=Decimal("100.00"),
        )
        self.session.add(self.acc_b)
        self.session.commit()

        self.client = TestClient(app)
        self.headers_a = {"Authorization": f"Bearer {create_access_token(self.user_a.id, self.user_a.email)}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_user_a_cannot_read_user_b_account(self):
        # User A requests User B's account ID -> 404
        res = self.client.get(f"/api/v1/accounts/{self.acc_b.id}", headers=self.headers_a)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "HTTP_404")

    def test_user_a_cannot_access_user_b_decisions(self):
        random_decision_id = uuid.uuid4()
        res = self.client.get(f"/api/v1/decisions/{random_decision_id}", headers=self.headers_a)
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
