"""
backend/tests/test_security/test_upload_security.py

Re-auditing file upload attacks: oversized payloads, malicious extensions, executables, path traversal.
"""
import io
import os
import unittest
import uuid
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine
from backend.ingestion.security import (
    MAX_FILE_SIZE_BYTES,
    QuarantineStorage,
    sanitize_filename,
    validate_file_content,
    FileOversizedError,
    InvalidFileTypeError,
    MaliciousContentError,
)


class TestUploadSecurity(unittest.TestCase):
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
        self.user = self.user_repo.create(f"upload_{uuid.uuid4().hex[:6]}@example.com", "Upload Tester")
        self.session.commit()
        self.token = create_access_token(self.user.id, self.user.email)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    # 14. Oversized upload rejected with 413
    def test_14_oversized_file_rejected(self):
        oversized = b"a" * (MAX_FILE_SIZE_BYTES + 10)
        with self.assertRaises(FileOversizedError):
            validate_file_content("huge.csv", oversized)

        files = {"file": ("huge.csv", oversized, "text/csv")}
        res = self.client.post("/api/v1/imports", files=files, headers=self.headers)
        self.assertEqual(res.status_code, 413)
        self.assertEqual(res.json()["code"], "FILE_TOO_LARGE")

    # 15. Malicious filenames sanitized against traversal
    def test_15_filename_path_traversal_sanitized(self):
        traversal_names = [
            "../../../etc/passwd.csv",
            "..\\..\\windows\\system32\\cmd.exe.csv",
            "....//....//shadow.csv",
        ]
        for bad_name in traversal_names:
            clean = sanitize_filename(bad_name)
            self.assertNotIn("/", clean)
            self.assertNotIn("\\", clean)
            self.assertNotIn("..", clean)
            self.assertTrue(clean.endswith(".csv"))

        # Null byte sanitization
        clean_null = sanitize_filename("test" + chr(0) + "hidden.csv")
        self.assertNotIn(chr(0), clean_null)
        self.assertTrue(clean_null.endswith(".csv"))

    # 16. Executable and binary magic byte payload rejection
    def test_16_executable_payload_rejected(self):
        pe_executable = b"MZ\x90\x00\x03\x00\x00\x00"  # Windows PE binary header
        with self.assertRaises(MaliciousContentError):
            validate_file_content("fake_statement.csv", pe_executable)

        elf_binary = b"\x7fELF\x02\x01\x01\x00"  # Linux ELF binary header
        with self.assertRaises(MaliciousContentError):
            validate_file_content("linux_binary.csv", elf_binary)

        zip_archive = b"PK\x03\x04\x14\x00\x00\x00"  # ZIP file
        with self.assertRaises(MaliciousContentError):
            validate_file_content("archive.csv", zip_archive)

    # 17. Quarantine storage isolates files by user UUID
    def test_17_quarantine_storage_isolation(self):
        storage = QuarantineStorage(base_dir="backend/ingestion/quarantine_test")
        try:
            content = b"date,description,amount\n2026-08-01,test,-10.00\n"
            path = storage.store_file(self.user.id, content)
            self.assertTrue(os.path.exists(path))
            self.assertIn(str(self.user.id), path)
            self.assertEqual(storage.read_file(path), content)
            storage.remove_file(path)
            self.assertFalse(os.path.exists(path))
        finally:
            import shutil
            shutil.rmtree("backend/ingestion/quarantine_test", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
