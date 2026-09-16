"""
Critical security tests ensuring tenant data isolation:
User A CANNOT read, modify, or delete User B records.
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import (
    UserRepository,
    ProfileRepository,
    AccountRepository,
    TransactionRepository,
    PurchaseRepository,
    TenantAccessError,
)
from backend.database.models.transaction import Transaction


class TestTenantIsolation(unittest.TestCase):
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

        # Create Tenant A and Tenant B
        self.user_a = self.user_repo.create(f"alice_{uuid.uuid4().hex[:6]}@tenant-a.com", "Alice")
        self.user_b = self.user_repo.create(f"bob_{uuid.uuid4().hex[:6]}@tenant-b.com", "Bob")
        self.session.commit()

        self.id_a = self.user_a.id
        self.id_b = self.user_b.id

        # Setup Tenant B's data
        self.repo_b_account = AccountRepository(self.session, self.id_b)
        self.account_b = self.repo_b_account.create("checking", "Bank B", "9999", "USD", Decimal("5000.0000"))

        self.repo_b_tx = TransactionRepository(self.session, self.id_b)
        self.tx_b = Transaction(
            user_id=self.id_b,
            dedup_hash="tx_b_secret_hash",
            transaction_date=date(2026, 9, 15),
            amount=Decimal("-100.0000"),
            currency="USD",
            amount_home=Decimal("-100.0000"),
            direction="debit",
            category="confidential",
            normalized_description="Confidential Expense",
            original_description="Confidential Expense",
            lifecycle_status="settled",
            cash_type="immediate_debit",
        )
        self.repo_b_tx.add(self.tx_b)

        self.repo_b_purchase = PurchaseRepository(self.session, self.id_b)
        self.purchase_b = self.repo_b_purchase.create(
            requested_amount=Decimal("1200.0000"),
            currency="USD",
            request_date=date(2026, 9, 15),
            desired_completion_date=date(2026, 9, 30),
            item_description="Bob Private Purchase",
        )
        self.session.commit()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_user_a_cannot_read_user_b_account(self):
        """User A querying Bob's account ID must return None."""
        repo_a = AccountRepository(self.session, self.id_a)
        result = repo_a.get_by_id(self.account_b.id)
        self.assertIsNone(result, "Security Breach: User A read User B account!")

    def test_user_a_cannot_read_user_b_transactions(self):
        """User A querying Bob's transaction by ID or hash must return None."""
        repo_a = TransactionRepository(self.session, self.id_a)
        res_by_id = repo_a.get_by_id(self.tx_b.id)
        self.assertIsNone(res_by_id, "Security Breach: User A read User B transaction by ID!")

        res_by_hash = repo_a.get_by_dedup_hash("tx_b_secret_hash")
        self.assertIsNone(res_by_hash, "Security Breach: User A read User B transaction by hash!")

    def test_user_a_cannot_delete_user_b_account(self):
        """User A attempting to delete Bob's account MUST raise TenantAccessError."""
        repo_a = AccountRepository(self.session, self.id_a)
        with self.assertRaises(TenantAccessError):
            repo_a.delete_by_id(self.account_b.id)

        # Confirm Bob's account still exists intact
        repo_b = AccountRepository(self.session, self.id_b)
        self.assertIsNotNone(repo_b.get_by_id(self.account_b.id))

    def test_user_a_cannot_add_entity_belonging_to_user_b(self):
        """Repository A refuses to add an entity created with user_id B."""
        repo_a = AccountRepository(self.session, self.id_a)
        from backend.database.models.account import FinancialAccount
        rogue_acc = FinancialAccount(
            user_id=self.id_b,  # Tenant B
            account_type="savings",
            institution_name="Sneaky",
            account_mask="0000",
            currency="USD",
            current_balance=Decimal("0"),
        )
        with self.assertRaises(TenantAccessError):
            repo_a.add(rogue_acc)


if __name__ == '__main__':
    unittest.main()
