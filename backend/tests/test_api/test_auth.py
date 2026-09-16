"""
backend/tests/test_api/test_auth.py
"""
import unittest
import uuid
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine


class TestAuthBoundary(unittest.TestCase):
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
        self.active_user = self.user_repo.create(f"active_{uuid.uuid4().hex[:6]}@example.com", "Active User")
        self.suspended_user = self.user_repo.create(f"suspended_{uuid.uuid4().hex[:6]}@example.com", "Suspended User")
        self.suspended_user.status = "suspended"
        self.session.commit()
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_missing_auth_header(self):
        res = self.client.get("/api/v1/profile")
        self.assertEqual(res.status_code, 401)
        data = res.json()
        self.assertEqual(data["code"], "HTTP_401")
        self.assertIn("Missing Authorization header", data["detail"])

    def test_malformed_auth_header(self):
        res = self.client.get("/api/v1/profile", headers={"Authorization": "Basic 12345"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid Authorization header format", res.json()["detail"])

    def test_raw_uuid_without_jwt_rejected(self):
        random_uuid = uuid.uuid4()
        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {random_uuid}"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid authentication token", res.json()["detail"])

    def test_nonexistent_user_token(self):
        ghost_token = create_access_token(uuid.uuid4(), "ghost@example.com")
        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {ghost_token}"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("User associated with token no longer exists", res.json()["detail"])

    def test_suspended_user_forbidden(self):
        token = create_access_token(self.suspended_user.id, self.suspended_user.email)
        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("User account is not active", res.json()["detail"])

    def test_valid_bearer_token(self):
        token = create_access_token(self.active_user.id, self.active_user.email)
        # Active user without profile gets 404 (not 401)
        res = self.client.get("/api/v1/profile", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 404)

    def test_openapi_security_scheme_bearer_jwt(self):
        openapi_res = self.client.get("/openapi.json")
        self.assertEqual(openapi_res.status_code, 200)
        spec = openapi_res.json()
        schemes = spec.get("components", {}).get("securitySchemes", {})
        self.assertIn("BearerAuth", schemes)
        self.assertEqual(schemes["BearerAuth"]["type"], "http")
        self.assertEqual(schemes["BearerAuth"]["scheme"], "bearer")
        self.assertEqual(schemes["BearerAuth"]["bearerFormat"], "JWT")

        # Protected endpoints must declare BearerAuth security
        paths = spec.get("paths", {})
        self.assertIn("/api/v1/profile", paths)
        self.assertEqual(paths["/api/v1/profile"]["get"]["security"], [{"BearerAuth": []}])
        self.assertEqual(paths["/api/v1/purchases/evaluate"]["post"]["security"], [{"BearerAuth": []}])

        # Public endpoints must not declare BearerAuth security
        self.assertNotIn("security", paths["/api/v1/auth/login"]["post"])


if __name__ == "__main__":
    unittest.main()
