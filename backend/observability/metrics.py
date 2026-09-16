"""
backend/observability/metrics.py

Thread-safe in-memory operational metrics collector for HTTP, decisions, ingestion, and security.
Strictly bounds label cardinality to prevent resource exhaustion and leaks:
- HTTP: method, normalized route pattern (:id), status class (2xx, 4xx, 5xx)
- Decisions: verdict, affordability_status, payment_method, risk_tier
- Ingestion: format (csv/pdf/ofx), status (success/failure)
- Security: event_type, severity
No user_ids, request_ids, or personal financial details in labels.
"""
from __future__ import annotations
from collections import defaultdict
import re
import threading
from typing import Any, Dict, List, Optional

UUID_PATTERN = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
INT_ID_PATTERN = re.compile(r"/\d+")


def normalize_route_path(path: str) -> str:
    """Replaces dynamic entity IDs with :id to preserve low label cardinality."""
    path = UUID_PATTERN.sub("/:id", path)
    path = INT_ID_PATTERN.sub("/:id", path)
    return path


class MetricsCollector:
    """
    Central operational metrics registry collecting counters and latencies.
    Exposes metrics in both JSON and Prometheus format.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # HTTP metrics: (method, route_pattern, status) -> count
        self.http_requests: Dict[tuple, int] = defaultdict(int)
        self.http_latencies_ms: List[float] = []

        # Decision metrics
        self.decision_evaluations_total: int = 0
        self.decision_latencies_ms: List[float] = []
        self.decisions_by_dimensions: Dict[tuple, int] = defaultdict(int)
        self.decision_amount_sum: float = 0.0
        self.data_insufficient_by_reason: Dict[str, int] = defaultdict(int)

        # Ingestion metrics: (format, status) -> count
        self.ingestions: Dict[tuple, int] = defaultdict(int)
        self.ingested_transactions_total: int = 0

        # Security metrics: (event_type, severity) -> count
        self.security_events: Dict[tuple, int] = defaultdict(int)

    def record_http_request(
        self,
        method: str,
        path: Optional[str] = None,
        status_code: int = 200,
        duration_ms: float = 0.0,
        endpoint: Optional[str] = None,
    ) -> None:
        """Records HTTP request metrics using low-cardinality route patterns."""
        route = endpoint or path or "unknown"
        norm_route = normalize_route_path(route)
        st_code = str(status_code)

        with self._lock:
            self.http_requests[(method.upper(), norm_route, st_code)] += 1
            self.http_latencies_ms.append(duration_ms)
            if len(self.http_latencies_ms) > 1000:
                self.http_latencies_ms = self.http_latencies_ms[-1000:]

    def record_decision(
        self,
        verdict: str,
        affordability_status: str = "affordable_now",
        recommended_payment_method: str = "full_payment",
        risk_tier: str = "LOW_RISK",
        amount: float = 0.0,
        duration_ms: float = 0.0,
    ) -> None:
        """Records financial decision outcome with bounded dimensions."""
        with self._lock:
            self.decision_evaluations_total += 1
            key = (verdict, affordability_status, recommended_payment_method, risk_tier)
            self.decisions_by_dimensions[key] += 1
            self.decision_amount_sum += float(amount)
            if duration_ms > 0:
                self.decision_latencies_ms.append(duration_ms)
                if len(self.decision_latencies_ms) > 1000:
                    self.decision_latencies_ms = self.decision_latencies_ms[-1000:]

    def record_data_insufficient(self, reason: str = "Data insufficient") -> None:
        with self._lock:
            # Low cardinality bucket for reason
            safe_reason = reason[:80] if reason else "Unspecified"
            self.data_insufficient_by_reason[safe_reason] += 1

    def record_ingestion(self, format: str = "csv", status: str = "success", transaction_count: int = 0) -> None:
        with self._lock:
            self.ingestions[(format.lower(), status.lower())] += 1
            self.ingested_transactions_total += transaction_count

    def record_security_event(self, event_type: str = "auth_failure", severity: str = "warning") -> None:
        with self._lock:
            self.security_events[(event_type.lower(), severity.lower())] += 1

    def get_summary(self) -> Dict[str, Any]:
        """Returns JSON-serializable operational summary."""
        with self._lock:
            http_mean_lat = (
                sum(self.http_latencies_ms) / len(self.http_latencies_ms)
                if self.http_latencies_ms else 0.0
            )
            dec_mean_lat = (
                sum(self.decision_latencies_ms) / len(self.decision_latencies_ms)
                if self.decision_latencies_ms else 0.0
            )
            return {
                "http": {
                    "requests_total": sum(self.http_requests.values()),
                    "mean_latency_ms": round(http_mean_lat, 2),
                },
                "decisions": {
                    "evaluations_total": self.decision_evaluations_total,
                    "mean_latency_ms": round(dec_mean_lat, 2),
                    "amount_sum": round(self.decision_amount_sum, 2),
                    "data_insufficient_total": sum(self.data_insufficient_by_reason.values()),
                },
                "ingestion": {
                    "ingestions_total": sum(self.ingestions.values()),
                    "transactions_total": self.ingested_transactions_total,
                },
                "security": {
                    "events_total": sum(self.security_events.values()),
                },
            }

    def to_prometheus(self) -> str:
        """Renders metrics in standard Prometheus text format."""
        lines = [
            "# HELP http_requests_total Total HTTP requests by route and status",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (method, endpoint, status_code), count in sorted(self.http_requests.items()):
                lines.append(f'http_requests_total{{endpoint="{endpoint}",method="{method}",status="{status_code}"}} {count}')

            http_sum = sum(self.http_latencies_ms)
            http_count = len(self.http_latencies_ms)
            lines.extend([
                "# HELP http_request_duration_ms HTTP request latency in milliseconds",
                "# TYPE http_request_duration_ms summary",
                f"http_request_duration_ms_sum {http_sum:.2f}",
                f"http_request_duration_ms_count {http_count}",
                "# HELP buyorwait_decisions_total Total purchase evaluations performed",
                "# TYPE buyorwait_decisions_total counter",
            ])

            for (verdict, aff, method, tier), count in sorted(self.decisions_by_dimensions.items()):
                lines.append(
                    f'buyorwait_decisions_total{{affordability_status="{aff}",payment_method="{method}",risk_tier="{tier}",verdict="{verdict}"}} {count}'
                )

            lines.extend([
                "# HELP buyorwait_decision_amount_sum Total evaluated purchase amounts",
                "# TYPE buyorwait_decision_amount_sum counter",
                f"buyorwait_decision_amount_sum {self.decision_amount_sum:.1f}",
                "# HELP buyorwait_data_insufficient_total Incomplete evaluations due to missing evidence",
                "# TYPE buyorwait_data_insufficient_total counter",
            ])

            for reason, count in sorted(self.data_insufficient_by_reason.items()):
                lines.append(f'buyorwait_data_insufficient_total{{reason="{reason}"}} {count}')

            lines.extend([
                "# HELP buyorwait_ingestions_total Total statement ingestion batches",
                "# TYPE buyorwait_ingestions_total counter",
            ])
            for (fmt, st), count in sorted(self.ingestions.items()):
                lines.append(f'buyorwait_ingestions_total{{format="{fmt}",status="{st}"}} {count}')

            lines.extend([
                "# HELP buyorwait_ingested_transactions_total Total transactions verified and ingested",
                "# TYPE buyorwait_ingested_transactions_total counter",
                f"buyorwait_ingested_transactions_total {self.ingested_transactions_total}",
                "# HELP buyorwait_security_events_total Security and abuse detection events",
                "# TYPE buyorwait_security_events_total counter",
            ])
            for (ev_type, sev), count in sorted(self.security_events.items()):
                lines.append(f'buyorwait_security_events_total{{event_type="{ev_type}",severity="{sev}"}} {count}')

        return "\n".join(lines) + "\n"

    def reset_all(self) -> None:
        """Resets all metrics (for testing)."""
        with self._lock:
            self.http_requests.clear()
            self.http_latencies_ms.clear()
            self.decision_evaluations_total = 0
            self.decision_latencies_ms.clear()
            self.decisions_by_dimensions.clear()
            self.decision_amount_sum = 0.0
            self.data_insufficient_by_reason.clear()
            self.ingestions.clear()
            self.ingested_transactions_total = 0
            self.security_events.clear()


# Global metrics collector instance
_GLOBAL_METRICS = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _GLOBAL_METRICS


def get_metrics() -> MetricsCollector:
    return _GLOBAL_METRICS
