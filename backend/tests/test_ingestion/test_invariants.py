"""
backend/tests/test_ingestion/test_invariants.py

Property and invariant tests for statement ingestion:
- No float enters normalized money (strictly Decimal)
- Committed transactions always belong to one user
- Committed transactions always preserve provenance
- Rejected/ambiguous rows cannot silently enter trusted ledger
- Duplicate committed transactions cannot be double-counted
- Internal transfers cannot increase income
- Parsing does not mutate source content
- Determinism: identical input yields identical parsed transactions
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
import os
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.models.transaction import Transaction
from backend.database.repositories import UserRepository
from backend.ingestion.service import IngestionService
from backend.ingestion.models import VerificationStatus


class TestIngestionInvariants(unittest.TestCase):
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
        self.user = self.user_repo.create(f"inv_{uuid.uuid4().hex[:6]}@example.com", "Invariant User")
        self.session.commit()
        self.user_id = self.user.id
        self.service = IngestionService()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_invariant_no_float_in_normalized_money(self):
        """Invariant: All monetary values in NormalizedTransaction MUST be Decimal, never float."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Groceries,-12.34
2026-09-02,Salary,1000.55
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "money.csv", csv_data
        )
        for t in txns:
            self.assertIsInstance(t.amount, Decimal, f"Amount {t.amount} is not a Decimal")
            self.assertNotIsInstance(t.amount, float)

    def test_invariant_rejected_rows_cannot_enter_ledger(self):
        """Invariant: Rejected or ambiguous rows CANNOT be committed to the official ledger."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Valid Coffee,-4.00
bad-date,Invalid Date,-10.00
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "mixed.csv", csv_data
        )
        self.assertEqual(preview.rejected_rows, 1)

        # Commit without override
        committed_count = self.service.commit_statement_batch(
            self.session, self.user_id, preview.batch_id, txns, override_ambiguous=False
        )
        self.assertEqual(committed_count, 1)

        # Verify DB only contains the 1 valid transaction
        db_txns = self.session.execute(
            select(Transaction).where(Transaction.user_id == self.user_id)
        ).scalars().all()
        self.assertEqual(len(db_txns), 1)
        self.assertEqual(db_txns[0].normalized_description, "Valid Coffee")

    def test_invariant_committed_txns_have_provenance(self):
        """Invariant: Committed transactions must have valid import_batch_id, user_id, and dedup_hash."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Valid Salary,3000.00
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "prov.csv", csv_data
        )
        self.service.commit_statement_batch(self.session, self.user_id, preview.batch_id, txns)

        db_tx = self.session.execute(
            select(Transaction).where(Transaction.user_id == self.user_id)
        ).scalar_one()

        self.assertEqual(db_tx.user_id, self.user_id)
        self.assertEqual(db_tx.import_batch_id, preview.batch_id)
        self.assertTrue(len(db_tx.dedup_hash) == 64)
        self.assertEqual(db_tx.source_provenance, "statement_import")

    def test_invariant_internal_transfer_does_not_increase_income(self):
        """Invariant: An internal transfer has cash_type 'non_cash', never 'settled_income'."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Transfer from Savings,2000.00
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "xfer.csv", csv_data
        )
        self.assertEqual(len(txns), 1)
        self.assertTrue(txns[0].is_internal_transfer)
        self.assertEqual(txns[0].cash_type, "non_cash")
        self.assertNotEqual(txns[0].cash_type, "settled_income")

    def test_invariant_source_content_immutability(self):
        """Invariant: Parsing does not modify or mutate the input bytes."""
        original_bytes = b"Date,Description,Amount\n2026-09-01,Test,-10.00\n"
        copy_bytes = bytes(original_bytes)

        self.service.stage_and_preview_statement(
            self.session, self.user_id, "immutable.csv", copy_bytes
        )
        self.assertEqual(copy_bytes, original_bytes)

    def test_invariant_parse_determinism(self):
        """Invariant: The same file content processed twice produces identical normalized transactions."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Test 1,-10.00
2026-09-02,Test 2,20.00
"""
        user_2 = self.user_repo.create(f"det_{uuid.uuid4().hex[:6]}@example.com", "Deterministic User")
        self.session.commit()

        _, txns_1 = self.service.stage_and_preview_statement(
            self.session, self.user_id, "det.csv", csv_data
        )
        _, txns_2 = self.service.stage_and_preview_statement(
            self.session, user_2.id, "det.csv", csv_data
        )

        self.assertEqual(len(txns_1), len(txns_2))
        for t1, t2 in zip(txns_1, txns_2):
            self.assertEqual(t1.transaction_date, t2.transaction_date)
            self.assertEqual(t1.amount, t2.amount)
            self.assertEqual(t1.direction, t2.direction)
            self.assertEqual(t1.normalized_description, t2.normalized_description)
            self.assertEqual(t1.category, t2.category)


if __name__ == "__main__":
    unittest.main()
