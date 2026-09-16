"""
backend/tests/test_security/test_tenant_isolation_and_enumeration.py

Comprehensive cross-tenant authorization and resource enumeration defense tests.
"""
from decimal import Decimal
import unittest
import uuid
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.database.models.account import FinancialAccount
from backend.database.models.decision import Decision
from backend.database.models.import_batch import ImportBatch
from backend.database.models.profile import FinancialProfile
from backend.database.models.purchase import PurchaseRequest
from backend.database.models.transaction import Transaction
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestTenantIsolationAndEnumeration(unittest.TestCase):
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
        self.user_repo = UserRepository(self.session)
        self.user_a = self.user_repo.create(f"usera_{uuid.uuid4().hex[:6]}@example.com", "Tenant A")
        self.user_b = self.user_repo.create(f"userb_{uuid.uuid4().hex[:6]}@example.com", "Tenant B")
        self.session.flush()

        # Seed resources for User B
        self.account_b = FinancialAccount(
            user_id=self.user_b.id,
            account_type="savings",
            institution_name="User B Savings",
            account_mask="1234",
            currency="USD",
            current_balance=Decimal("15000.00"),
            status="active",
        )
        self.session.add(self.account_b)

        self.import_b = ImportBatch(
            user_id=self.user_b.id,
            filename="user_b_statement.csv",
            content_hash="fake_sha_b_" + uuid.uuid4().hex,
            upload_status="completed",
            parsing_status="parsed",
            verification_status="unverified",
        )
        self.session.add(self.import_b)
        self.session.flush()

        self.purchase_b = PurchaseRequest(
            user_id=self.user_b.id,
            item_description="Secret B Item",
            merchant_name="Secret Merchant",
            category="electronics",
            requested_amount=Decimal("5000.00"),
            currency="USD",
            request_date=__import__("datetime").date(2026, 9, 15),
            desired_completion_date=__import__("datetime").date(2026, 11, 15),
            allows_partial_payment=True,
            payment_options_data=[],
        )
        self.session.add(self.purchase_b)
        self.session.flush()

        self.decision_b = Decision(
            user_id=self.user_b.id,
            purchase_request_id=self.purchase_b.id,
            verdict="WAIT",
            amount_safe_to_pay=Decimal("0.00"),
            affordability_status="affordable_later",
            recommended_payment_method="wait",
            payment_plan="none",
            earliest_date_for_full_payment=__import__("datetime").date(2026, 10, 1),
            spending_changes_needed="none",
            decision_explanation="Private User B decision explanation.",
            risk_tier="HIGH_RISK",
        )
        self.session.add(self.decision_b)
        self.session.commit()

        self.token_a = create_access_token(self.user_a.id, self.user_a.email)
        self.headers_a = {"Authorization": f"Bearer {self.token_a}"}
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    # 9. Cross-tenant read returns 404 (prevent resource enumeration)
    def test_09_cross_tenant_read_returns_404(self):
        # User A tries to view User B's account
        res_acct = self.client.get(f"/api/v1/accounts/{self.account_b.id}", headers=self.headers_a)
        self.assertEqual(res_acct.status_code, 404)
        self.assertIn(res_acct.json()["code"], ("HTTP_404", "RESOURCE_NOT_FOUND"))

        # User A tries to view User B's import
        res_imp = self.client.get(f"/api/v1/imports/{self.import_b.id}", headers=self.headers_a)
        self.assertEqual(res_imp.status_code, 404)

        # User A tries to view User B's decision
        res_dec = self.client.get(f"/api/v1/decisions/{self.decision_b.id}", headers=self.headers_a)
        self.assertEqual(res_dec.status_code, 404)

    # 10. Cross-tenant mutate returns 404
    def test_10_cross_tenant_mutate_returns_404(self):
        # User A tries to verify User B's import
        res = self.client.post(f"/api/v1/imports/{self.import_b.id}/verify", headers=self.headers_a)
        self.assertEqual(res.status_code, 404)

    # 11. Predictable ID resource enumeration returns 404 without leaking info
    def test_11_predictable_resource_enumeration_defense(self):
        random_id = uuid.uuid4()
        for endpoint in [f"/api/v1/accounts/{random_id}", f"/api/v1/imports/{random_id}", f"/api/v1/decisions/{random_id}"]:
            res = self.client.get(endpoint, headers=self.headers_a)
            self.assertEqual(res.status_code, 404)
            self.assertIn(res.json()["code"], ("HTTP_404", "RESOURCE_NOT_FOUND"))
            detail_lower = res.json()["detail"].lower()
            self.assertTrue("not found" in detail_lower or "does not exist" in detail_lower)

    # 24. Unauthorized decision access explicitly verified
    def test_24_unauthorized_decision_access(self):
        # User A explicitly denied access to User B's purchase decision
        res = self.client.get(f"/api/v1/decisions/{self.decision_b.id}", headers=self.headers_a)
        self.assertEqual(res.status_code, 404)
        self.assertIn(res.json()["code"], ("HTTP_404", "RESOURCE_NOT_FOUND"))



if __name__ == "__main__":
    unittest.main()
