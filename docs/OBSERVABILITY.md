# System Observability Architecture

**Buy or Wait? Financial Decision Support Platform**  
**Milestone 7: Observability + Grounded Explanation**

---

## 1. Overview & Architectural Principles

The Buy or Wait? platform implements comprehensive application observability designed for financial decision-making systems. Its core architectural principles ensure complete visibility without compromising tenant data privacy:

1. **Correlation Across System Boundaries**: Every request carries an `X-Request-ID` or `X-Correlation-ID` header, generated at ingress and propagated across middleware, application services, database operations, and audit logs.
2. **Structured Single-Line JSON Logs**: Machine-readable logs parsed effortlessly by log aggregation engines (Datadog, Loki, CloudWatch) without multiline breakage.
3. **Zero PII / Sensitive Data Leakage**: Automated recursive redaction of credentials, session tokens, authorization headers, account numbers, and private payloads.
4. **Low-Cardinality Metrics**: Strict bounding of metric labels to avoid Prometheus memory explosion; dynamic entity IDs are normalized to `:id`.
5. **Clear Separation of Liveness vs. Readiness**: Uncoupled health endpoints distinguishing HTTP container viability from deep downstream dependency availability.

---

## 2. Request Correlation & Context

The `ObservabilityMiddleware` coordinates request tracking:

- **Ingress Header Extraction**: Inspects `X-Request-ID` or `X-Correlation-ID`. If absent, generates a standard UUIDv4.
- **State Attachment**: Attaches `request.state.request_id` for use in exception handlers, route handlers, and service calls.
- **Egress Propagation**: Appends `X-Request-ID` and `X-Response-Time` to every HTTP response.

```text
Client Request
      ↓  (X-Request-ID: req_8923f...)
ObservabilityMiddleware
      ↓  (request.state.request_id = req_8923f...)
FastAPI Route / Application Service
      ↓  (audit_repo.log(..., structured_metadata={"request_id": ...}))
PostgreSQL (Audit Trail)
      ↓
HTTP Response (Headers: X-Request-ID, X-Response-Time: 14.20ms)
```

---

## 3. Sensitive Data Redaction

The `backend/observability/redactor.py` module enforces redaction across both structured key-value dictionaries and freeform text:

### Sensitive Key Scrubbing
Any dictionary key matching `password`, `token`, `access_token`, `refresh_token`, `authorization`, `jwt_secret_key`, `secret`, `raw_statement`, `file_content`, `account_number`, `ssn`, or `credit_card` is replaced with `"[REDACTED]"`. Authorization headers formatted as `Bearer <token>` are masked to `Bearer [REDACTED]`.

### Regex Token & Numeric Scrubbing
- **JWT Pattern**: `eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}` → `"[REDACTED]"`
- **Bearer Header Pattern**: `(?i)bearer\s+[a-zA-Z0-9_\-\.]+` → `"Bearer [REDACTED]"`
- **Long Numeric Account Sequence**: `\d{10,16}` → `"[REDACTED]"` (scrubs account and card numbers while preserving short IDs and dates).

---

## 4. Operational Metrics Registry

The `MetricsCollector` in `backend/observability/metrics.py` provides thread-safe, in-memory aggregation of operational events:

### Bounded Label Dimensions
| Metric Family | Metric Name | Type | Bounded Labels |
|---|---|---|---|
| HTTP Traffic | `http_requests_total` | Counter | `method`, `endpoint` (e.g. `/api/v1/accounts/:id`), `status` |
| HTTP Latency | `http_request_duration_ms` | Summary | `sum`, `count` |
| Decisioning | `buyorwait_decisions_total` | Counter | `verdict`, `affordability_status`, `payment_method`, `risk_tier` |
| Decision Volume | `buyorwait_decision_amount_sum` | Counter | N/A (Total currency volume evaluated) |
| Quality Gates | `buyorwait_data_insufficient_total`| Counter | `reason` (truncated low-cardinality string) |
| Ingestion | `buyorwait_ingestions_total` | Counter | `format` (csv/pdf/ofx), `status` (success/failure) |
| Ingestion Rows | `buyorwait_ingested_transactions_total` | Counter | N/A (Total transactions verified) |
| Security | `buyorwait_security_events_total` | Counter | `event_type`, `severity` |

### Prometheus Scrape Endpoint
The endpoint `GET /api/v1/metrics` renders standard Prometheus text exposition format:
```text
# HELP http_requests_total Total HTTP requests by route and status
# TYPE http_requests_total counter
http_requests_total{endpoint="/api/v1/health",method="GET",status="200"} 42
http_requests_total{endpoint="/api/v1/purchases/evaluate",method="POST",status="200"} 18

# HELP buyorwait_decisions_total Total purchase evaluations performed
# TYPE buyorwait_decisions_total counter
buyorwait_decisions_total{affordability_status="affordable_now",payment_method="full_payment",risk_tier="LOW_RISK",verdict="BUY"} 15
buyorwait_decisions_total{affordability_status="affordable_later",payment_method="wait",risk_tier="HIGH_RISK",verdict="WAIT"} 3
```

---

## 5. Health, Liveness, and Readiness Probes

The service implements distinct liveness and readiness probes conforming to Kubernetes requirements:

### `GET /api/v1/health/liveness`
- **Purpose**: Verifies that the ASGI container process is responsive.
- **Dependency Checks**: None. Returns HTTP 200 immediately.
- **Failure Consequence**: Container restart if unresponsive.

### `GET /api/v1/health/readiness`
- **Purpose**: Verifies that the container is ready to accept production traffic.
- **Dependency Checks**: Executes active SQL ping (`SELECT 1`) against PostgreSQL.
- **Success Response**: HTTP 200 `{"status": "ready", "database": "connected", "dependencies": {"database": "healthy"}}`
- **Failure Response**: HTTP 503 `{"status": "unready", "database": "disconnected", "dependencies": {"database": "unreachable"}}`
- **Traffic Impact**: Service orchestrators remove the pod from the routing pool until database connectivity recovers.

---

## 6. Audit Logging & Rejection Traces

All purchase evaluations and data quality rejections emit immutable audit records into the `audit_events` table:

### Evaluation Rejection (`DATA_INSUFFICIENT`)
```json
{
  "status": "DATA_INSUFFICIENT",
  "rejection_code": "DATA_INSUFFICIENT",
  "reason": "Missing active checking account balance.",
  "reason_category": "accounts",
  "remediation_required": "Link or upload statements for an active checking account.",
  "request_id": "req-89231",
  "engine_version": "1.0.0",
  "decision_policy_version": "shadow_audit_only"
}
```

### Evaluation Success
```json
{
  "purchase_request_id": "123e4567-e89b-12d3-a456-426614174000",
  "verdict": "BUY",
  "amount_safe_to_pay": "250.00",
  "affordability_status": "affordable_now",
  "recommended_payment_method": "full_payment",
  "risk_tier": "LOW_RISK",
  "engine_version": "1.0.0",
  "calibration_version": "v3_empirical_q90_20260914",
  "decision_policy_version": "shadow_audit_only"
}
```
