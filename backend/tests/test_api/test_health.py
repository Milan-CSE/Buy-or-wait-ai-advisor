"""
backend/tests/test_api/test_health.py
"""
import unittest
from fastapi.testclient import TestClient
from backend.api.main import app


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_public_endpoint(self):
        res = self.client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["api_version"], "1.0.0")
        self.assertEqual(data["engine_version"], "1.0.0")
        self.assertEqual(data["risk_calibration_version"], "v3_empirical_q90_20260914")
        self.assertIn("timestamp", data)

        # Check security and observability headers
        self.assertIn("x-request-id", res.headers)
        self.assertIn("x-response-time", res.headers)
        self.assertEqual(res.headers.get("x-frame-options"), "DENY")
        self.assertEqual(res.headers.get("x-content-type-options"), "nosniff")


if __name__ == "__main__":
    unittest.main()
