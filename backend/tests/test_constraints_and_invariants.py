"""
Tests verifying database constraints, uniqueness, foreign-key cascades, and rollback.
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import UserRepository, ProfileRepository
from backend.database.models.user import User
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction


import os

class TestConstraintsAndInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        cls.engine = get_engine(db_url)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = SessionFactory
        cls.SessionLocal.configure(bind=cls.engine)

    def setUp(self):
        self.session: Session = self.SessionLocal()
        self.user_repo = UserRepository(self.session)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_unique_email_constraint(self):
        """Duplicate emails must raise IntegrityError."""
        email = f"unique_{uuid.uuid4().hex[:6]}@example.com"
        self.user_repo.create(email, "User 1")
        self.session.commit()

        self.user_repo.create(email, "User 2")
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_one_profile_per_user_uniqueness(self):
        """Each user can have at most one FinancialProfile."""
        user = self.user_repo.create(f"prof_{uuid.uuid4().hex[:6]}@example.com", "User")
        self.session.commit()

        p1 = FinancialProfile(
            user_id=user.id,
            home_currency="USD",
            current_available_balance=Decimal("100"),
            minimum_balance_to_keep=Decimal("50"),
            protected_categories=[],
            reducible_categories=[],
            stoppable_categories=[],
            payment_methods=[],
        )
        self.session.add(p1)
        self.session.commit()

        p2 = FinancialProfile(
            user_id=user.id,  # duplicate user_id
            home_currency="EUR",
            current_available_balance=Decimal("200"),
            minimum_balance_to_keep=Decimal("50"),
            protected_categories=[],
            reducible_categories=[],
            stoppable_categories=[],
            payment_methods=[],
        )
        self.session.add(p2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_foreign_key_cascade_delete(self):
        """Deleting a User cascades and removes their FinancialProfile and Transactions."""
        user = self.user_repo.create(f"cascade_{uuid.uuid4().hex[:6]}@example.com", "User")
        self.session.commit()
        uid = user.id

        prof_repo = ProfileRepository(self.session, uid)
        prof_repo.save_or_update("USD", Decimal("1000"), Decimal("200"))

        tx = Transaction(
            user_id=uid,
            dedup_hash=f"tx_cascade_{uuid.uuid4().hex[:6]}",
            transaction_date=date(2026, 9, 15),
            amount=Decimal("-50"),
            currency="USD",
            amount_home=Decimal("-50"),
            direction="debit",
            category="groceries",
            normalized_description="Groceries",
            original_description="Groceries",
            lifecycle_status="settled",
            cash_type="immediate_debit",
        )
        self.session.add(tx)
        self.session.commit()

        # Delete user
        self.user_repo.delete(uid)
        self.session.commit()

        # Confirm child profile and tx are removed
        self.assertIsNone(prof_repo.get_profile())
        from sqlalchemy import select
        tx_check = self.session.execute(select(Transaction).where(Transaction.user_id == uid)).scalar_one_or_none()
        self.assertIsNone(tx_check)

    def test_transaction_rollback_behavior(self):
        """Verify rollback reverts partial transactions."""
        user = self.user_repo.create(f"roll_{uuid.uuid4().hex[:6]}@example.com", "User")
        self.session.commit()

        tx_hash = f"tx_to_rollback_{uuid.uuid4().hex[:6]}"
        tx = Transaction(
            user_id=user.id,
            dedup_hash=tx_hash,
            transaction_date=date(2026, 9, 15),
            amount=Decimal("-50"),
            currency="USD",
            amount_home=Decimal("-50"),
            direction="debit",
            category="groceries",
            normalized_description="Groceries",
            original_description="Groceries",
            lifecycle_status="settled",
            cash_type="immediate_debit",
        )
        self.session.add(tx)
        # Rollback without commit
        self.session.rollback()

        from sqlalchemy import select
        found = self.session.execute(select(Transaction).where(Transaction.dedup_hash == tx_hash)).scalar_one_or_none()
        self.assertIsNone(found)


if __name__ == '__main__':
    unittest.main()
