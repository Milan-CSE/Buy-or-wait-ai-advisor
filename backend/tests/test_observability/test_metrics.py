"""
backend/tests/test_observability/test_metrics.py

Tests for MetricsCollector, Prometheus export format, and label cardinality bounds.
"""
from backend.observability.metrics import MetricsCollector


class TestMetrics:
    def test_http_request_recording_and_normalization(self):
        collector = MetricsCollector()
        # Test normal endpoint
        collector.record_http_request("GET", "/api/v1/health", 200, 12.5)
        # Test path normalization for UUIDs
        collector.record_http_request("GET", "/api/v1/accounts/123e4567-e89b-12d3-a456-426614174000", 200, 25.0)
        # Test integer ID normalization
        collector.record_http_request("GET", "/api/v1/users/99", 200, 18.2)

        prom = collector.to_prometheus()
        assert 'http_requests_total{endpoint="/api/v1/health",method="GET",status="200"} 1' in prom
        assert 'http_requests_total{endpoint="/api/v1/accounts/:id",method="GET",status="200"} 1' in prom
        assert 'http_requests_total{endpoint="/api/v1/users/:id",method="GET",status="200"} 1' in prom
        assert "http_request_duration_ms_count" in prom

    def test_decision_outcome_metrics(self):
        collector = MetricsCollector()
        collector.record_decision(
            verdict="BUY",
            affordability_status="affordable_now",
            recommended_payment_method="full_payment",
            risk_tier="LOW_RISK",
            amount=250.0,
        )
        collector.record_decision(
            verdict="WAIT",
            affordability_status="affordable_later",
            recommended_payment_method="wait",
            risk_tier="MODERATE_RISK",
            amount=500.0,
        )

        prom = collector.to_prometheus()
        assert 'buyorwait_decisions_total{affordability_status="affordable_now",payment_method="full_payment",risk_tier="LOW_RISK",verdict="BUY"} 1' in prom
        assert 'buyorwait_decisions_total{affordability_status="affordable_later",payment_method="wait",risk_tier="MODERATE_RISK",verdict="WAIT"} 1' in prom
        assert "buyorwait_decision_amount_sum 750.0" in prom

    def test_data_insufficient_metrics(self):
        collector = MetricsCollector()
        collector.record_data_insufficient("Missing active checking account")

        prom = collector.to_prometheus()
        assert 'buyorwait_data_insufficient_total{reason="Missing active checking account"} 1' in prom

    def test_ingestion_and_security_metrics(self):
        collector = MetricsCollector()
        collector.record_ingestion(format="csv", status="success", transaction_count=45)
        collector.record_security_event(event_type="auth_failure", severity="warning")

        prom = collector.to_prometheus()
        assert 'buyorwait_ingestions_total{format="csv",status="success"} 1' in prom
        assert "buyorwait_ingested_transactions_total 45" in prom
        assert 'buyorwait_security_events_total{event_type="auth_failure",severity="warning"} 1' in prom
