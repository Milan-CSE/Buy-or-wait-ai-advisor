from backend.auth.jwt import create_access_token
"""
backend/tests/test_api/test_imports_api.py
"""
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestImportsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        cls.engine = get_engine(db_url)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = SessionFactory
        cls.SessionLocal.configure(bind=cls.engine)

    def setUp(self):
        from backend.auth.rate_limiter import get_rate_limiter
        get_rate_limiter().reset_all()
        self.session = self.SessionLocal()
        self.user = UserRepository(self.session).create(f"imp_{uuid.uuid4().hex[:6]}@example.com", "Import User")
        self.session.commit()
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user.id, self.user.email)}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_upload_preview_verify_flow(self):
        csv_content = b"Date,Description,Amount\n2026-01-15,Payroll Employer,3500.00\n2026-01-18,Safeway Groceries,-85.50\n2026-01-20,Monthly Rent,-800.00\n"

        # 1. Upload statement
        files = {"file": ("statement.csv", csv_content, "text/csv")}
        up_res = self.client.post("/api/v1/imports", files=files, headers=self.headers)
        self.assertEqual(up_res.status_code, 201)
        batch_id = up_res.json()["batch_id"]
        self.assertEqual(up_res.json()["total_rows"], 3)

        # 2. Get Preview
        prev_res = self.client.get(f"/api/v1/imports/{batch_id}/preview", headers=self.headers)
        self.assertEqual(prev_res.status_code, 200)
        self.assertEqual(prev_res.json()["total_rows"], 3)
        self.assertEqual(prev_res.json()["accepted_rows"], 3)

        # 3. Verify and Commit
        ver_res = self.client.post(f"/api/v1/imports/{batch_id}/verify", json={"override_ambiguous": False}, headers=self.headers)
        self.assertEqual(ver_res.status_code, 200)
        self.assertEqual(ver_res.json()["committed_rows"], 3)

        # 4. Verify transactions appear in transactions endpoint
        tx_res = self.client.get("/api/v1/transactions", headers=self.headers)
        self.assertEqual(tx_res.status_code, 200)
        self.assertEqual(tx_res.json()["total"], 3)

    def test_duplicate_file_rejected(self):
        csv_content = b"Date,Description,Amount\n2026-01-15,Payroll,3000.00\n"
        files = {"file": ("statement_dup.csv", csv_content, "text/csv")}

        res1 = self.client.post("/api/v1/imports", files=files, headers=self.headers)
        self.assertEqual(res1.status_code, 201)

        # Second upload of same content -> 409 Conflict
        files2 = {"file": ("statement_dup.csv", csv_content, "text/csv")}
        res2 = self.client.post("/api/v1/imports", files=files2, headers=self.headers)
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.json()["code"], "DUPLICATE_FILE")

    def test_disallowed_file_extension(self):
        files = {"file": ("malicious.exe", b"MZbad", "application/octet-stream")}
        res = self.client.post("/api/v1/imports", files=files, headers=self.headers)
        self.assertIn(res.status_code, (415, 422))


if __name__ == "__main__":
    unittest.main()
