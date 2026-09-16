"""
backend/tests/test_security/test_abuse_and_rate_limiting.py

Rate limiting enforcement, HTTP 429 Retry-After verification, and brute force protection.
"""
import unittest
import uuid
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.auth.rate_limiter import get_rate_limiter
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestAbuseAndRateLimiting(unittest.TestCase):
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
            email=f"abuse_{uuid.uuid4().hex[:6]}@example.com",
            full_name="Abuse Tester",
            password_hash=__import__("backend.auth.passwords", fromlist=["hash_password"]).hash_password("Pass1234#"),
        )
        self.session.commit()
        self.token = create_access_token(self.user.id, self.user.email)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        get_rate_limiter().reset_all()
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        get_rate_limiter().reset_all()

    # 12. Rate limiting enforcement returns 429 with Retry-After header
    def test_12_auth_rate_limit_breach_returns_429(self):
        get_rate_limiter().reset_all()
        # RATE_LIMIT_AUTH is 5 requests/minute
        test_ip = "192.168.1.100"
        headers = {"X-Forwarded-For": test_ip}
        statuses = []
        for i in range(6):
            res = self.client.post(
                "/api/v1/auth/login",
                json={"email": f"test_{i}@example.com", "password": "WrongPassword123#"},
                headers=headers,
            )
            statuses.append(res.status_code)

        # At least one request should be rate limited with 429
        self.assertIn(429, statuses)
        # Check that last status is 429 and has Retry-After
        last_res = self.client.post(
            "/api/v1/auth/login",
            json={"email": "excess@example.com", "password": "WrongPassword123#"},
            headers=headers,
        )
        self.assertEqual(last_res.status_code, 429)
        self.assertEqual(last_res.json()["code"], "RATE_LIMIT_EXCEEDED")
        self.assertIn("Retry-After", last_res.headers)
        self.assertTrue(int(last_res.headers["Retry-After"]) >= 1)

    # 13. Brute force login protection
    def test_13_brute_force_failed_login_protection(self):
        get_rate_limiter().reset_all()
        limiter = get_rate_limiter()
        test_ip = "192.168.1.200"
        headers = {"X-Forwarded-For": test_ip}
        # Trigger 5 failed logins for this user from test_ip
        for _ in range(5):
            limiter.record_failed_login(test_ip, self.user.email)

        # Next login attempt should be throttled even with correct credentials
        res = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.user.email, "password": "Pass1234#"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 429)
        self.assertIn("too many failed login attempts", res.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
