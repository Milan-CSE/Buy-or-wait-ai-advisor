"""
backend/tests/test_security/test_idempotency_and_audit.py

Security tests for tenant-scoped idempotency keys and immutable audit event logging.
"""
from decimal import Decimal
import unittest
import uuid
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.database.models.audit import AuditEvent
from backend.database.models.profile import FinancialProfile
from backend.database.models.account import FinancialAccount
from backend.database.models.transaction import Transaction
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestIdempotencyAndAuditSecurity(unittest.TestCase):
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
        self.user_a = self.user_repo.create(f"audit_a_{uuid.uuid4().hex[:6]}@example.com", "Tenant A")
        self.user_b = self.user_repo.create(f"audit_b_{uuid.uuid4().hex[:6]}@example.com", "Tenant B")
        self.session.commit()
        self.token_a = create_access_token(self.user_a.id, self.user_a.email)
        self.token_b = create_access_token(self.user_b.id, self.user_b.email)
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    # 22. Audit events generated on security operations without sensitive leakage
    def test_22_audit_event_generation(self):
        # Register user
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": f"audit_rec_{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123#",
            "full_name": "Audit Recorded",
        })
        self.assertEqual(reg_res.status_code, 201)
        new_user_id = uuid.UUID(reg_res.json()["user_id"])

        # Check audit event in DB
        events = self.session.query(AuditEvent).filter(AuditEvent.user_id == new_user_id).all()
        self.assertTrue(len(events) >= 1)
        reg_event = [e for e in events if e.event_type == "user_registered"][0]
        self.assertIsNotNone(reg_event.timestamp)
        # Ensure password or hash is never in audit payload!
        self.assertNotIn("password", reg_event.structured_metadata)
        self.assertNotIn("password_hash", reg_event.structured_metadata)

    # 23. Idempotency keys isolated per user
    def test_23_idempotency_key_tenant_isolation(self):
        # Set up financial profile and account for User A
        prof = FinancialProfile(
            user_id=self.user_a.id,
            home_currency="USD",
            current_available_balance=Decimal("5000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
            reserve_policy="strict_minimum",
            protected_categories=["rent"],
            reducible_categories=["dining"],
            stoppable_categories=["streaming"],
            payment_methods=["full_payment"],
        )
        self.session.add(prof)
        acct = FinancialAccount(
            user_id=self.user_a.id,
            account_type="checking",
            institution_name="User A Checking",
            account_mask="1234",
            currency="USD",
            current_balance=Decimal("5000.00"),
            status="active",
        )
        self.session.add(acct)
        self.session.flush()

        # Add 3 transactions across 15 days so DataQuality passes
        ref_date = __import__("datetime").date(2026, 9, 15)
        for i in range(3):
            t = Transaction(
                user_id=self.user_a.id,
                account_id=acct.id,
                transaction_date=ref_date - __import__("datetime").timedelta(days=i * 6),
                original_description=f"Transaction {i}",
                normalized_description=f"Transaction {i}",
                amount=Decimal("-50.00"),
                amount_home=Decimal("-50.00"),
                currency="USD",
                category="groceries",
                direction="debit",
                dedup_hash=f"dedup_tx_{i}_" + uuid.uuid4().hex,
                lifecycle_status="settled",
                confidence_state="verified",
            )
            self.session.add(t)
        self.session.commit()

        shared_idemp_key = f"key_{uuid.uuid4().hex}"
        payload = {
            "item_description": "Desk Chair",
            "merchant_name": "IKEA",
            "category": "furniture",
            "requested_amount": "200.00",
            "currency": "USD",
            "request_date": "2026-09-15",
        }

        # User A evaluates purchase with shared_idemp_key
        res_a = self.client.post(
            "/api/v1/purchases/evaluate",
            json=payload,
            headers={"Authorization": f"Bearer {self.token_a}", "X-Idempotency-Key": shared_idemp_key},
        )
        self.assertEqual(res_a.status_code, 200)

        # User B using the SAME idempotency key should NOT get User A's cached response!
        # Because User B has no profile, User B must get 422 DATA_INSUFFICIENT (isolated evaluation)
        res_b = self.client.post(
            "/api/v1/purchases/evaluate",
            json=payload,
            headers={"Authorization": f"Bearer {self.token_b}", "X-Idempotency-Key": shared_idemp_key},
        )
        self.assertEqual(res_b.status_code, 422)


if __name__ == "__main__":
    unittest.main()
