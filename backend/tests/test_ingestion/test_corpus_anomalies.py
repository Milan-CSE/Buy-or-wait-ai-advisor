"""
backend/tests/test_ingestion/test_corpus_anomalies.py

Tests anomalous rows, edge cases, and verification checkpoints:
7. Malformed rows (unexpected column counts)
8. Missing values (missing dates, empty amounts)
11. Internal transfers between user accounts
12. Ambiguous signs (both Debit and Credit populated)
13. Unknown categories (clean fallback to 'other')
15. Mixed valid/invalid rows (partial rejection, triggers NEEDS_REVIEW)
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
import os
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import UserRepository, AccountRepository
from backend.ingestion.service import IngestionService
from backend.ingestion.models import IngestionState, VerificationStatus


class TestCorpusAnomalies(unittest.TestCase):
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
        self.user = self.user_repo.create(f"anomaly_{uuid.uuid4().hex[:6]}@example.com", "Anomaly User")
        self.session.commit()
        self.user_id = self.user.id
        self.service = IngestionService()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_07_and_15_malformed_and_mixed_rows(self):
        """Case 7 & 15: Handles rows with missing columns, invalid dates, and valid rows."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Valid Groceries,-45.00
not-a-date,Malformed Date,-10.00
2026-09-02,Valid Dining,-25.00
2026-09-03,Incomplete Row
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "mixed_statement.csv", csv_data
        )

        self.assertEqual(preview.total_rows, 4)
        self.assertEqual(preview.accepted_rows, 2)
        self.assertEqual(preview.rejected_rows, 2)
        # Because invalid rows exist, preview MUST require user review
        self.assertTrue(preview.requires_user_review)
        self.assertEqual(preview.state, IngestionState.NEEDS_REVIEW)

        # Confirm rejected rows are tagged properly
        self.assertEqual(txns[0].verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(txns[1].verification_status, VerificationStatus.REJECTED)
        self.assertEqual(txns[2].verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(txns[3].verification_status, VerificationStatus.REJECTED)

    def test_08_missing_values(self):
        """Case 8: Rejects rows with completely blank amounts or dates."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Blank Amount,
,Blank Date,-50.00
2026-09-03,Valid Salary,2000.00
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "missing_values.csv", csv_data
        )
        self.assertEqual(preview.accepted_rows, 1)
        self.assertEqual(preview.rejected_rows, 2)
        self.assertEqual(txns[2].amount, Decimal("2000.0000"))

    def test_11_internal_transfers(self):
        """Case 11: Accurately tags internal account transfers without treating them as income/expense."""
        # Create user account
        acc_repo = AccountRepository(self.session, self.user_id)
        acc_repo.create("checking", "Chase Checking", "1234", "USD", Decimal("5000.00"))
        acc_repo.create("savings", "Chase Savings", "5678", "USD", Decimal("10000.00"))
        self.session.commit()

        csv_data = b"""Date,Description,Amount
2026-09-05,Transfer to Savings,-500.00
2026-09-06,Online Transfer from Checking,500.00
2026-09-07,Internal Transfer to Account,-200.00
2026-09-08,Regular Starbucks Coffee,-5.50
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "transfers.csv", csv_data
        )

        self.assertEqual(preview.accepted_rows, 4)

        # First 3 should be detected as internal transfers
        self.assertTrue(txns[0].is_internal_transfer)
        self.assertEqual(txns[0].category, "transfer")
        self.assertEqual(txns[0].cash_type, "non_cash")

        self.assertTrue(txns[1].is_internal_transfer)
        self.assertEqual(txns[1].category, "transfer")
        self.assertEqual(txns[1].cash_type, "non_cash")

        self.assertTrue(txns[2].is_internal_transfer)
        self.assertEqual(txns[2].category, "transfer")
        self.assertEqual(txns[2].cash_type, "non_cash")

        # 4th is an actual expense
        self.assertFalse(txns[3].is_internal_transfer)
        self.assertEqual(txns[3].category, "dining")
        self.assertEqual(txns[3].cash_type, "immediate_debit")

    def test_12_ambiguous_signs_dual_columns(self):
        """Case 12: Flags row as AMBIGUOUS when both Debit and Credit are populated."""
        csv_data = b"""Date,Description,Debit,Credit
2026-09-05,Ambiguous Entry,50.00,100.00
2026-09-06,Clear Expense,40.00,
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "ambiguous.csv", csv_data
        )

        self.assertEqual(preview.ambiguous_rows, 1)
        self.assertEqual(preview.accepted_rows, 1)
        self.assertEqual(preview.state, IngestionState.NEEDS_REVIEW)
        self.assertEqual(txns[0].verification_status, VerificationStatus.AMBIGUOUS)
        self.assertIn("both Debit and Credit", txns[0].ambiguity_reason)

    def test_13_unknown_categories(self):
        """Case 13: Unmatched descriptions cleanly categorize to 'other'."""
        csv_data = b"""Date,Description,Amount
2026-09-01,XYZ Strange Vendor Unrecognized,-12.34
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "unknown.csv", csv_data
        )
        self.assertEqual(preview.accepted_rows, 1)
        self.assertEqual(txns[0].category, "other")
        self.assertEqual(txns[0].category_reason, "unmatched_fallback")


if __name__ == "__main__":
    unittest.main()
