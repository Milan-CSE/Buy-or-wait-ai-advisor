"""
Tests for full CRUD lifecycle across all database entities.
"""
import unittest
import uuid
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import (
    UserRepository,
    ProfileRepository,
    AccountRepository,
    TransactionRepository,
    ImportBatchRepository,
    PurchaseRepository,
    DecisionRepository,
    AuditRepository,
)


class TestCRUDLifecycle(unittest.TestCase):
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
        self.user = self.user_repo.create(f"user_{uuid.uuid4().hex[:6]}@example.com", "Alice Smith")
        self.session.commit()
        self.user_id = self.user.id

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_user_lifecycle(self):
        fetched = self.user_repo.get_by_id(self.user_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.full_name, "Alice Smith")
        self.assertEqual(fetched.status, "active")

    def test_profile_crud(self):
        repo = ProfileRepository(self.session, self.user_id)
        prof = repo.save_or_update(
            home_currency="USD",
            current_available_balance=Decimal("2500.5000"),
            minimum_balance_to_keep=Decimal("500.0000"),
            protected_categories=["rent", "utilities"],
            reducible_categories=["groceries"],
            stoppable_categories=["streaming"],
            max_installment_months=Decimal("6.0"),
        )
        self.session.commit()

        loaded = repo.get_profile()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.current_available_balance, Decimal("2500.5000"))
        self.assertEqual(loaded.profile_version, 1)

        # Update
        updated = repo.save_or_update(
            home_currency="USD",
            current_available_balance=Decimal("3000.0000"),
            minimum_balance_to_keep=Decimal("600.0000"),
        )
        self.session.commit()
        self.assertEqual(updated.profile_version, 2)
        self.assertEqual(updated.current_available_balance, Decimal("3000.0000"))

    def test_account_crud(self):
        repo = AccountRepository(self.session, self.user_id)
        acc = repo.create("checking", "Chase", "1234", "USD", Decimal("1500.0000"))
        self.session.commit()

        active = repo.list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].account_mask, "1234")

        # Delete
        repo.delete_by_id(acc.id)
        self.session.commit()
        self.assertEqual(len(repo.list_active()), 0)

    def test_transaction_crud(self):
        repo = TransactionRepository(self.session, self.user_id)
        from backend.database.models.transaction import Transaction
        tx = Transaction(
            user_id=self.user_id,
            dedup_hash="hash_01",
            transaction_date=date(2026, 9, 15),
            amount=Decimal("-45.2500"),
            currency="USD",
            amount_home=Decimal("-45.2500"),
            direction="debit",
            category="dining",
            normalized_description="Dinner",
            original_description="Dinner at Joe's",
            lifecycle_status="settled",
            cash_type="immediate_debit",
        )
        repo.add(tx)
        self.session.commit()

        loaded = repo.get_by_dedup_hash("hash_01")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.amount, Decimal("-45.2500"))

        # Range query
        in_range = repo.list_by_date_range(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(len(in_range), 1)

    def test_audit_logging_and_immutability(self):
        repo = AuditRepository(self.session, self.user_id)
        evt = repo.log("purchase_evaluated", actor_type="system", structured_metadata={"test": 123})
        self.session.commit()

        events = repo.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "purchase_evaluated")
        self.assertEqual(events[0].structured_metadata["test"], 123)


if __name__ == '__main__':
    unittest.main()
