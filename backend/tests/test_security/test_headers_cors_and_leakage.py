"""
backend/tests/test_security/test_headers_cors_and_leakage.py

Verification of security response headers, strict CORS, and prevention of internal information disclosure.
"""
import unittest
import uuid
from fastapi.testclient import TestClient

from backend.api.config import settings
from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestHeadersCorsAndLeakage(unittest.TestCase):
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
        self.user = self.user_repo.create(
            email=f"header_{uuid.uuid4().hex[:6]}@example.com",
            full_name="Header Tester",
            password_hash=__import__("backend.auth.passwords", fromlist=["hash_password"]).hash_password("SecretPass123!"),
        )
        self.session.commit()
        self.token = create_access_token(self.user.id, self.user.email)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    # 18. Strict Security Headers present on responses
    def test_18_security_headers_present(self):
        res = self.client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("max-age=31536000", res.headers.get("Strict-Transport-Security", ""))
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("default-src 'none'", res.headers.get("Content-Security-Policy", ""))

    # 19. Cache-Control: no-store on sensitive authenticated routes
    def test_19_cache_control_on_sensitive_routes(self):
        res = self.client.get("/api/v1/accounts", headers=self.headers)
        self.assertIn("no-store", res.headers.get("Cache-Control", ""))
        self.assertIn("no-cache", res.headers.get("Cache-Control", ""))

    # 20. Strict CORS origin handling
    def test_20_strict_cors_configuration(self):
        # Whitelisted origin allowed
        allowed_res = self.client.get(
            "/api/v1/health",
            headers={"Origin": "http://localhost:3000"}
        )
        self.assertEqual(allowed_res.headers.get("access-control-allow-origin"), "http://localhost:3000")

        # Disallowed origin does not get Access-Control-Allow-Origin header
        evil_res = self.client.get(
            "/api/v1/health",
            headers={"Origin": "https://evil-hacker-site.com"}
        )
        self.assertIsNone(evil_res.headers.get("access-control-allow-origin"))

    # 21. No internal information or secrets in error responses
    def test_21_no_internal_secrets_in_errors(self):
        # Malformed request triggering validation error
        res = self.client.post("/api/v1/purchases/evaluate", json={"invalid": True}, headers=self.headers)
        body = res.text
        # Assert secret key, SQL keywords, and python tracebacks are not in response body
        self.assertNotIn(settings.JWT_SECRET_KEY, body)
        self.assertNotIn("Traceback (most recent call last)", body)
        self.assertNotIn("SELECT", body)
        self.assertNotIn("password_hash", body)


if __name__ == "__main__":
    unittest.main()
