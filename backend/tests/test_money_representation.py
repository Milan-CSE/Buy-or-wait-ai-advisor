"""
Tests verifying exact Decimal monetary precision, scale, and absence of float drift.
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import UserRepository, ProfileRepository, TransactionRepository
from backend.database.models.transaction import Transaction


class TestMoneyRepresentation(unittest.TestCase):
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
        self.user = self.user_repo.create(f"money_{uuid.uuid4().hex[:6]}@example.com", "Money Test")
        self.session.commit()
        self.user_id = self.user.id

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_four_decimal_places_exactness(self):
        """Verify 4 decimal places are preserved without rounding or float conversion."""
        exact_amount = Decimal("1234567.8901")
        exact_min = Decimal("987.6543")

        prof_repo = ProfileRepository(self.session, self.user_id)
        prof_repo.save_or_update(
            home_currency="USD",
            current_available_balance=exact_amount,
            minimum_balance_to_keep=exact_min,
        )
        self.session.commit()

        loaded = prof_repo.get_profile()
        self.assertIsInstance(loaded.current_available_balance, Decimal)
        self.assertEqual(loaded.current_available_balance, exact_amount)
        self.assertEqual(loaded.minimum_balance_to_keep, exact_min)

    def test_negative_debit_amount_persistence(self):
        """Verify negative amounts persist accurately with Decimal type."""
        exact_debit = Decimal("-499.9999")
        tx_repo = TransactionRepository(self.session, self.user_id)
        tx = Transaction(
            user_id=self.user_id,
            dedup_hash="tx_money_hash",
            transaction_date=date(2026, 9, 15),
            amount=exact_debit,
            currency="EUR",
            amount_home=exact_debit,
            direction="debit",
            category="electronics",
            normalized_description="Test Debit",
            original_description="Test Debit",
            lifecycle_status="settled",
            cash_type="immediate_debit",
        )
        tx_repo.add(tx)
        self.session.commit()

        loaded = tx_repo.get_by_dedup_hash("tx_money_hash")
        self.assertIsInstance(loaded.amount, Decimal)
        self.assertEqual(loaded.amount, exact_debit)


if __name__ == '__main__':
    unittest.main()
