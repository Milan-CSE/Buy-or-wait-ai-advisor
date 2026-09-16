"""
backend/tests/test_observability/test_health_and_readiness.py

Tests for /health/liveness, /health/readiness, and /metrics endpoints.
"""
from fastapi.testclient import TestClient
from backend.api.main import app


class TestHealthAndReadiness:
    def test_liveness_probe_returns_200(self):
        client = TestClient(app)
        res = client.get("/api/v1/health/liveness")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "alive"
        assert "timestamp" in data

    def test_readiness_probe_verifies_database_connectivity(self):
        client = TestClient(app)
        res = client.get("/api/v1/health/readiness")
        # In current test runtime with PostgreSQL running, should be 200 ready
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert data["dependencies"]["database"] == "healthy"

    def test_metrics_scrape_endpoint_returns_prometheus_text(self):
        client = TestClient(app)
        res = client.get("/api/v1/metrics")
        assert res.status_code == 200
        assert "text/plain" in res.headers["content-type"]
        body = res.text
        assert "# HELP http_requests_total" in body
        assert "# TYPE http_requests_total counter" in body
