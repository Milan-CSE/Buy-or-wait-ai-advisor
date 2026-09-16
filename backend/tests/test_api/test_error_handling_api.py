"""
backend/tests/test_api/test_error_handling_api.py
"""
import unittest
from fastapi.testclient import TestClient
from backend.api.main import app


class TestErrorHandlingRFC7807(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_404_rfc7807_format(self):
        res = self.client.get("/api/v1/non_existent_endpoint")
        self.assertEqual(res.status_code, 404)
        data = res.json()
        self.assertIn("type", data)
        self.assertIn("title", data)
        self.assertEqual(data["status"], 404)
        self.assertIn("detail", data)
        self.assertIn("instance", data)
        self.assertEqual(data["code"], "HTTP_404")

    def test_401_rfc7807_format(self):
        res = self.client.get("/api/v1/profile")
        self.assertEqual(res.status_code, 401)
        data = res.json()
        self.assertEqual(data["status"], 401)
        self.assertEqual(data["code"], "HTTP_401")
        self.assertIn("request_id", data)


if __name__ == "__main__":
    unittest.main()
