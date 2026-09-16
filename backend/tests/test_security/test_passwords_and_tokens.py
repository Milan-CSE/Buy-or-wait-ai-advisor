"""
backend/tests/test_security/test_passwords_and_tokens.py

Security tests for Argon2id password hashing, password policy, and JWT token lifecycle.
"""
from datetime import timedelta
import unittest
import uuid
import jwt
from fastapi.testclient import TestClient

from backend.api.config import settings
from backend.api.main import app
from backend.auth.jwt import (
    create_access_token,
    decode_access_token,
    TokenExpiredError,
    InvalidTokenError,
)
from backend.auth.passwords import (
    hash_password,
    verify_password,
    validate_password_strength,
    PasswordPolicyError,
)
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestPasswordsAndTokens(unittest.TestCase):
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
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    # 1. Password hashing (Argon2id format, unique salt)
    def test_01_argon2id_password_hashing(self):
        pw = "StrongPassw0rd!2026"
        h1 = hash_password(pw)
        h2 = hash_password(pw)

        self.assertTrue(h1.startswith("$argon2id$"))
        self.assertIn("m=65536,t=2,p=1", h1)
        # Unique salts ensure different hashes for same password
        self.assertNotEqual(h1, h2)
        self.assertTrue(verify_password(h1, pw))
        self.assertTrue(verify_password(h2, pw))

    # 2. Password policy rejection
    def test_02_password_policy_rejection(self):
        weak_passwords = [
            ("short1!", "at least 8 characters"),
            ("nouppercase123!", "uppercase letter"),
            ("NOLOWERCASE123!", "lowercase letter"),
            ("NoNumbersHere!", "numeric digit"),
            ("NoSpecialChars123", "special character"),
        ]
        for weak_pw, expected_msg in weak_passwords:
            with self.assertRaises(PasswordPolicyError) as ctx:
                validate_password_strength(weak_pw)
            self.assertIn(expected_msg, str(ctx.exception))

    # 3. Incorrect password rejection
    def test_03_incorrect_password_verification(self):
        h = hash_password("ValidPassword123#")
        self.assertFalse(verify_password(h, "WrongPassword123#"))
        self.assertFalse(verify_password(h, ""))
        self.assertFalse(verify_password(None, "ValidPassword123#"))
        self.assertFalse(verify_password("invalid_hash_string", "ValidPassword123#"))

    # 4. Expired token rejection
    def test_04_expired_token_rejected(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "user@example.com", expires_delta=timedelta(seconds=-10))
        with self.assertRaises(TokenExpiredError):
            decode_access_token(token)

        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("expired", res.json()["detail"].lower())

    # 5. Malformed token rejection
    def test_05_malformed_token_rejected(self):
        malformed = "not.a.valid.jwt.token"
        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {malformed}"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("invalid", res.json()["detail"].lower())

    # 6. Wrong token type rejection
    def test_06_wrong_token_type_rejected(self):
        user_id = uuid.uuid4()
        refresh_token = create_access_token(
            user_id, "user@example.com", custom_claims={"type": "refresh"}
        )
        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {refresh_token}"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("type", res.json()["detail"].lower())

    # 7. Invalid signature rejection
    def test_07_invalid_signature_rejected(self):
        user_id = uuid.uuid4()
        evil_key = "completely-wrong-key-used-for-tampering-token-signature!"
        payload = {
            "sub": str(user_id),
            "email": "user@example.com",
            "jti": str(uuid.uuid4()),
            "type": "access",
            "iss": settings.TOKEN_ISSUER,
            "aud": settings.TOKEN_AUDIENCE,
            "exp": 9999999999,
            "iat": 1000000000,
        }
        forged_token = jwt.encode(payload, evil_key, algorithm="HS256")
        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {forged_token}"})
        self.assertEqual(res.status_code, 401)

    # 8. Token revocation on logout
    def test_08_token_revocation_logout(self):
        # Register and login a real user
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": f"rev_{uuid.uuid4().hex[:6]}@example.com",
            "password": "Password123!",
            "full_name": "Revoke Tester",
        })
        self.assertEqual(reg_res.status_code, 201)
        email = reg_res.json()["email"]

        login_res = self.client.post("/api/v1/auth/login", json={
            "email": email,
            "password": "Password123!",
        })
        self.assertEqual(login_res.status_code, 200)
        token = login_res.json()["access_token"]

        # Token works before logout
        me_res = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_res.status_code, 200)

        # Logout revokes token
        logout_res = self.client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout_res.status_code, 200)

        # Reusing revoked token is immediately rejected with 401
        revoked_res = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(revoked_res.status_code, 401)
        self.assertIn("revoked", revoked_res.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
