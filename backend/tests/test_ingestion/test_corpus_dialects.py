"""
backend/tests/test_ingestion/test_corpus_dialects.py

Tests parsing and normalizing synthetic statements across real-world dialect shapes:
1. Normal standard CSV (Date, Description, Amount)
2. Separate Debit/Credit columns (Date, Details, Debit, Credit)
3. Signed amount column (- for debits, + for credits)
4. Opposite / Inverted sign convention (Credit card format)
5. Currency symbols ($ € £ ₹ ¥) and thousands commas ($1,234.56)
6. Diverse date formats (YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, DD-Mon-YYYY)
7. Multiline descriptions with quotes
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
import os
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import UserRepository
from backend.ingestion.service import IngestionService
from backend.ingestion.models import IngestionState, VerificationStatus


class TestCorpusDialects(unittest.TestCase):
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
        self.user = self.user_repo.create(f"dialect_{uuid.uuid4().hex[:6]}@example.com", "Dialect User")
        self.session.commit()
        self.user_id = self.user.id
        self.service = IngestionService()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_01_normal_csv_with_amount_column(self):
        """Case 1: Standard CSV with Date, Description, Amount."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Tech Employer Direct Deposit,3500.00
2026-09-02,Whole Foods Supermarket,-84.50
2026-09-03,Metro Subway Transit,-4.75
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "standard_statement.csv", csv_data
        )

        self.assertEqual(preview.total_rows, 3)
        self.assertEqual(preview.accepted_rows, 3)
        self.assertEqual(preview.rejected_rows, 0)
        self.assertEqual(preview.state, IngestionState.VERIFIED)

        # Assert Decimal values and directions
        self.assertEqual(txns[0].amount, Decimal("3500.0000"))
        self.assertEqual(txns[0].direction, "credit")
        self.assertEqual(txns[0].category, "salary")

        self.assertEqual(txns[1].amount, Decimal("-84.5000"))
        self.assertEqual(txns[1].direction, "debit")
        self.assertEqual(txns[1].category, "groceries")

        self.assertEqual(txns[2].amount, Decimal("-4.7500"))
        self.assertEqual(txns[2].direction, "debit")
        self.assertEqual(txns[2].category, "transport")

    def test_02_separate_debit_credit_columns(self):
        """Case 2: Separate Debit and Credit columns (e.g. UK/Indian bank format)."""
        csv_data = b"""Txn Date,Particulars,Withdrawal,Deposit,Balance
05/09/2026,Monthly Apartment Rent,1400.00,,5600.00
10/09/2026,Consulting Client Payout,,1250.00,6850.00
12/09/2026,Starbucks Coffee,6.50,,6843.50
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "debit_credit_bank.csv", csv_data
        )

        self.assertEqual(preview.total_rows, 3)
        self.assertEqual(preview.accepted_rows, 3)
        self.assertEqual(txns[0].amount, Decimal("-1400.0000"))
        self.assertEqual(txns[0].direction, "debit")
        self.assertEqual(txns[0].category, "rent")

        self.assertEqual(txns[1].amount, Decimal("1250.0000"))
        self.assertEqual(txns[1].direction, "credit")

        self.assertEqual(txns[2].amount, Decimal("-6.5000"))
        self.assertEqual(txns[2].direction, "debit")
        self.assertEqual(txns[2].category, "dining")

    def test_03_signed_amount_column(self):
        """Case 3: Signed Amount column with explicit +/- prefix."""
        csv_data = b"""Posting Date,Details,Transaction Amount
2026-08-15,Payroll Bonus,+500.00
2026-08-16,Amazon Retail Purchase,-64.99
2026-08-17,Netflix Subscription,-15.99
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "signed_statement.csv", csv_data
        )
        self.assertEqual(preview.accepted_rows, 3)
        self.assertEqual(txns[0].amount, Decimal("500.0000"))
        self.assertEqual(txns[1].amount, Decimal("-64.9900"))
        self.assertEqual(txns[1].category, "shopping")
        self.assertEqual(txns[2].amount, Decimal("-15.9900"))
        self.assertEqual(txns[2].category, "entertainment")

    def test_04_opposite_sign_convention(self):
        """Case 4: Credit card statement where charges are positive and payments are negative."""
        csv_data = b"""Date,Description,Amount
2026-09-05,Target Store,120.50
2026-09-06,Uber Ride,24.00
2026-09-07,Autopay Payment Received,-144.50
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "credit_card.csv", csv_data, sign_convention="inverted"
        )
        self.assertEqual(preview.accepted_rows, 3)
        # Target purchase should be inverted to negative (debit)
        self.assertEqual(txns[0].amount, Decimal("-120.5000"))
        self.assertEqual(txns[0].direction, "debit")
        # Uber ride should be inverted to negative (debit)
        self.assertEqual(txns[1].amount, Decimal("-24.0000"))
        self.assertEqual(txns[1].direction, "debit")
        # Payment received should be inverted to positive (credit)
        self.assertEqual(txns[2].amount, Decimal("144.5000"))
        self.assertEqual(txns[2].direction, "credit")

    def test_05_currency_symbols_and_thousands_commas(self):
        """Case 5: Handles currency symbols ($ € £ ₹) and commas (e.g. '$1,500.25')."""
        csv_data = b"""Date,Description,Amount
2026-09-10,Salary Credit,"$2,500.00"
2026-09-11,Electric Bill Utility,"-$1,250.75"
2026-09-12,Euro Booking Fee,"(1,050.00)"
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "formatted_symbols.csv", csv_data
        )
        self.assertEqual(preview.accepted_rows, 3)
        self.assertEqual(txns[0].amount, Decimal("2500.0000"))
        self.assertEqual(txns[1].amount, Decimal("-1250.7500"))
        self.assertEqual(txns[1].category, "utilities")
        # Accounting format (1,050.00) normalized to -1050.0000
        self.assertEqual(txns[2].amount, Decimal("-1050.0000"))

    def test_06_diverse_date_formats(self):
        """Case 6: Recognizes YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, and DD-Mon-YYYY."""
        csv_data = b"""Date,Description,Amount
15-Sep-2026,Grocery Shopper,-55.00
2026-09-16,Pharmacy Clinic,-30.00
"""
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "diverse_dates.csv", csv_data
        )
        self.assertEqual(preview.accepted_rows, 2)
        self.assertEqual(txns[0].transaction_date, date(2026, 9, 15))
        self.assertEqual(txns[1].transaction_date, date(2026, 9, 16))
        self.assertEqual(txns[1].category, "healthcare")

    def test_14_multiline_descriptions(self):
        """Case 14: Quoted fields containing newlines and commas."""
        csv_data = b'''Date,Description,Amount
2026-09-08,"Best Buy
Store #421
San Francisco, CA",-320.00
2026-09-09,Simple Coffee,-4.50
'''
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "multiline.csv", csv_data
        )
        self.assertEqual(preview.accepted_rows, 2)
        # Multiline should be collapsed into clean single line
        self.assertEqual(txns[0].normalized_description, "Best Buy Store #421 San Francisco, CA")
        self.assertEqual(txns[0].amount, Decimal("-320.0000"))
        self.assertEqual(txns[0].category, "shopping")


if __name__ == "__main__":
    unittest.main()
