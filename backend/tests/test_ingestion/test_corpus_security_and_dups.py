"""
backend/tests/test_ingestion/test_corpus_security_and_dups.py

Tests security defenses and deduplication boundaries:
9. Duplicate file detection
10. Duplicate transaction detection (in-batch and cross-batch)
16. Malicious filename / path traversal defenses
17. Oversized file defense (>10MB)
18. Disallowed file types and executable binary signatures
19. Cross-user isolation during commit
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
import os
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import UserRepository
from backend.database.repositories.base import TenantAccessError
from backend.ingestion.service import IngestionService, DuplicateFileError
from backend.ingestion.security import (
    FileOversizedError,
    InvalidFileTypeError,
    MaliciousContentError,
    sanitize_filename,
)
from backend.ingestion.models import VerificationStatus


class TestCorpusSecurityAndDups(unittest.TestCase):
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
        self.user_a = self.user_repo.create(f"sec_a_{uuid.uuid4().hex[:6]}@example.com", "User A")
        self.user_b = self.user_repo.create(f"sec_b_{uuid.uuid4().hex[:6]}@example.com", "User B")
        self.session.commit()
        self.id_a = self.user_a.id
        self.id_b = self.user_b.id
        self.service = IngestionService()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_09_duplicate_file_detection(self):
        """Case 9: Staging the exact same file twice for the same user raises DuplicateFileError."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Groceries Supermarket,-50.00
"""
        preview1, txns1 = self.service.stage_and_preview_statement(
            self.session, self.id_a, "file1.csv", csv_data
        )
        self.service.commit_statement_batch(self.session, self.id_a, preview1.batch_id, txns1)

        # Upload identical file content again
        with self.assertRaises(DuplicateFileError):
            self.service.stage_and_preview_statement(
                self.session, self.id_a, "file2_renamed.csv", csv_data
            )

    def test_10_duplicate_transactions_detection(self):
        """Case 10: In-batch duplicates and cross-batch duplicates are marked DUPLICATE."""
        # Statement 1
        csv_1 = b"""Date,Description,Amount
2026-09-01,Rent Apartment,-1200.00
2026-09-02,Electric Utility,-100.00
"""
        prev1, txns1 = self.service.stage_and_preview_statement(self.session, self.id_a, "batch1.csv", csv_1)
        self.service.commit_statement_batch(self.session, self.id_a, prev1.batch_id, txns1)

        # Statement 2 contains an overlapping transaction + an internal duplicate within itself
        csv_2 = b"""Date,Description,Amount
2026-09-01,Rent Apartment,-1200.00
2026-09-03,New Book,-25.00
2026-09-03,New Book,-25.00
"""
        prev2, txns2 = self.service.stage_and_preview_statement(self.session, self.id_a, "batch2.csv", csv_2)

        self.assertEqual(prev2.total_rows, 3)
        self.assertEqual(prev2.accepted_rows, 1)  # Only the first 'New Book' is new
        self.assertEqual(prev2.duplicate_rows, 2)  # 'Rent Apartment' + second 'New Book'
        self.assertEqual(txns2[0].verification_status, VerificationStatus.DUPLICATE)
        self.assertEqual(txns2[1].verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(txns2[2].verification_status, VerificationStatus.DUPLICATE)

    def test_16_malicious_filename_and_path_traversal(self):
        """Case 16: Path traversal attempts in filenames are stripped to safe basenames."""
        evil_name1 = "../../../../etc/passwd.csv"
        evil_name2 = "..\\..\\windows\\system32\\calc.csv"
        evil_name3 = "valid\0evil.csv"

        clean1 = sanitize_filename(evil_name1)
        clean2 = sanitize_filename(evil_name2)
        clean3 = sanitize_filename(evil_name3)

        self.assertEqual(clean1, "passwd.csv")
        self.assertEqual(clean2, "calc.csv")
        self.assertEqual(clean3, "validevil.csv")

    def test_17_oversized_file_rejection(self):
        """Case 17: Uploads larger than 10MB are rejected before parsing."""
        oversized_bytes = b"Date,Description,Amount\n" + (b"2026-09-01,Spam,-1.00\n" * 500000)
        # Verify it exceeds 10MB
        if len(oversized_bytes) > 10 * 1024 * 1024:
            with self.assertRaises(FileOversizedError):
                self.service.stage_and_preview_statement(
                    self.session, self.id_a, "big.csv", oversized_bytes
                )

    def test_18_disallowed_file_types_and_binaries(self):
        """Case 18: Disallows PDFs, executables (MZ / ELF), and ZIP archives."""
        # 1. Invalid extension
        with self.assertRaises(InvalidFileTypeError):
            self.service.stage_and_preview_statement(
                self.session, self.id_a, "report.pdf", b"%PDF-1.4 Fake PDF Content"
            )

        # 2. Windows PE executable disguised as .csv
        fake_pe = b"MZ\x90\x00\x03\x00\x00\x00Date,Description,Amount"
        with self.assertRaises(MaliciousContentError):
            self.service.stage_and_preview_statement(
                self.session, self.id_a, "malware.csv", fake_pe
            )

        # 3. ZIP archive disguised as .csv
        fake_zip = b"PK\x03\x04\x14\x00\x00\x00Date,Description,Amount"
        with self.assertRaises(MaliciousContentError):
            self.service.stage_and_preview_statement(
                self.session, self.id_a, "archive.csv", fake_zip
            )

        # 4. Embedded null bytes
        fake_null = b"Date,Description,Amount\n2026-09-01,Evil\x00Payload,-50.00"
        with self.assertRaises(MaliciousContentError):
            self.service.stage_and_preview_statement(
                self.session, self.id_a, "null.csv", fake_null
            )

    def test_19_cross_user_upload_access(self):
        """Case 19: User B cannot commit User A's import batch."""
        csv_data = b"""Date,Description,Amount
2026-09-01,Private Spend,-100.00
"""
        preview_a, txns_a = self.service.stage_and_preview_statement(
            self.session, self.id_a, "private.csv", csv_data
        )

        # User B attempts to commit User A's batch
        with self.assertRaises(TenantAccessError):
            self.service.commit_statement_batch(
                self.session, self.id_b, preview_a.batch_id, txns_a
            )


if __name__ == "__main__":
    unittest.main()
