# Operations Runbook — Buy or Wait? Production API

## 1. Service Overview

| Component | Technology | Role |
|---|---|---|
| API Server | FastAPI + Uvicorn | REST API, authentication, rate limiting |
| Database | PostgreSQL 16 | User data, financial data, decisions, audit log |
| File Quarantine | Local disk / Render persistent disk | Uploaded statement storage |
| Domain Engine | buyorwait_engine (pure Python) | Financial decision logic (database-agnostic) |

**Default port**: 8000  
**Health check**: `GET /api/v1/health/liveness` → HTTP 200  
**DB health check**: `GET /api/v1/health/readiness` → HTTP 200  
**Metrics**: `GET /api/v1/metrics` → Prometheus text format

---

## 2. Health Monitoring

### Liveness probe
```bash
curl -s http://localhost:8000/api/v1/health/liveness
# Expected: {"status": "ok"}
```

### Readiness probe (includes DB connectivity)
```bash
curl -s http://localhost:8000/api/v1/health/readiness
# Expected: {"status": "ready", "database": "connected"}
```

### Full health status
```bash
curl -s http://localhost:8000/api/v1/health
# Returns: version, uptime, environment
```

### Metrics scrape
```bash
curl -s http://localhost:8000/api/v1/metrics
# Returns Prometheus text format with:
# - http_requests_total{endpoint,method,status}
# - buyorwait_decisions_total{verdict,affordability_status,payment_method,risk_tier}
# - buyorwait_data_insufficient_total{reason}
# - buyorwait_ingestions_total{format,status}
# - buyorwait_security_events_total{event_type,severity}
```

---

## 3. Log Format

All logs are structured JSON to stdout. Fields:

```json
{
  "timestamp": "2026-09-15T12:00:00.000Z",
  "level": "INFO",
  "logger": "backend.api.routers.purchases",
  "message": "Purchase evaluation complete",
  "request_id": "req_abc123",
  "user_id": "user_uuid_here",
  "verdict": "BUY",
  "risk_tier": "LOW_RISK",
  "duration_ms": 245
}
```

Sensitive data is automatically redacted:
- JWT tokens → `[REDACTED]`
- Bearer headers → `Bearer [REDACTED]`  
- Account numbers (10-16 digits) → `[REDACTED]`
- Dict keys: `password`, `token`, `secret`, `key`, `credential` → `[REDACTED]`

---

## 4. Common Operational Tasks

### 4.1 Database health check

```bash
# From host (requires psql)
psql $DATABASE_URL -c "SELECT 1;"

# From API (via health endpoint)
curl -s http://localhost:8000/api/v1/health/readiness | jq .database
```

### 4.2 Check migration status

```bash
alembic current
alembic history --verbose
```

### 4.3 Apply new migrations

```bash
alembic upgrade head
```

Always run migrations before deploying new API code that depends on schema changes.

### 4.4 Check active connections to PostgreSQL

```bash
psql $DATABASE_URL -c "
SELECT count(*), state
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY state;
"
```

---

## 5. Failure Scenarios and Recovery

### 5.1 Database connection failure

**Symptoms**: `/api/v1/health/readiness` returns non-200, all API endpoints return 500.

**Recovery**:
1. Verify PostgreSQL is running: `docker ps` or check Render PostgreSQL dashboard
2. Verify `DATABASE_URL` environment variable is correct
3. Check connection limits: `SELECT count(*) FROM pg_stat_activity;`
4. Restart API service if DB was temporarily unavailable

### 5.2 JWT secret key mismatch (after secret rotation)

**Symptoms**: All authenticated requests return 401 with "Invalid token" even for recently logged-in users.

**Recovery**:
1. Set new `JWT_SECRET_KEY` in environment
2. Restart API service
3. Users must log in again (all existing tokens are invalidated — this is expected behavior)

**Note**: Token revocation blacklist (`revoked_tokens` table) persists across restarts. Rotate the key only when intentionally invalidating all sessions.

### 5.3 Malformed file upload causes ingestion error

**Symptoms**: Upload endpoint returns 422 or 400.

**Recovery**:
1. Check `backend/ingestion/quarantine/` — file may be quarantined with failure reason
2. Review structured logs for `ingestion_error` events
3. User must re-upload a valid CSV/OFX file
4. No database state is corrupted — ingestion is atomic

### 5.4 Financial engine raises exception during evaluation

**Symptoms**: Purchase evaluation endpoint returns 500.

**Recovery**:
1. Check structured logs for `engine_exception` events — the full traceback is logged
2. Verify financial profile data quality: `GET /api/v1/profile`
3. Check that account balances and transaction data are complete
4. The exception does NOT partially commit data — evaluation is atomic

### 5.5 Rate limit triggered for legitimate user

**Symptoms**: User receives 429 with `Retry-After` header.

**Recovery**:
1. Wait for the rate limit window to reset (1 minute sliding window)
2. Adjust rate limit env vars if legitimate usage patterns exceed limits
3. Check `buyorwait_security_events_total{event_type="rate_limit"}` metrics for frequency

### 5.6 Disk full (quarantine storage)

**Symptoms**: File uploads return 500 or "No space left on device" in logs.

**Recovery**:
1. Check disk usage: `df -h /app/backend/ingestion/quarantine`
2. Remove old quarantined files (verified transactions are stored in DB, not disk)
3. Expand disk on Render dashboard
4. Consider periodic cleanup job for quarantine directory

---

## 6. Security Events

Security events are logged with structured metadata and counted in metrics.

| Event Type | Severity | Meaning |
|---|---|---|
| `auth_failure` | warning | Invalid password or non-existent user |
| `rate_limit` | warning | IP/user exceeded rate limit |
| `invalid_token` | warning | Malformed or revoked JWT |
| `cross_tenant_access` | critical | Access attempt to another user's data |
| `upload_rejected` | warning | File failed magic byte or size validation |
| `path_traversal` | critical | Attempted directory traversal in filename |

Check recent security events:
```bash
# From metrics
curl -s http://localhost:8000/api/v1/metrics | grep security_events

# From structured logs (jq filter)
# <your log aggregator> | jq 'select(.event_type == "cross_tenant_access")'
```

---

## 7. Performance Benchmarks

Under local test conditions (single process, SQLite for unit tests):

| Operation | P50 | P95 | P99 |
|---|---|---|---|
| `GET /api/v1/health/liveness` | < 5ms | < 10ms | < 20ms |
| `POST /api/v1/auth/login` | < 200ms | < 400ms | < 600ms |
| `POST /api/v1/purchases/evaluate` | < 500ms | < 1200ms | < 2000ms |
| CSV ingestion (500 rows) | < 300ms | < 600ms | < 1000ms |

Login is dominated by Argon2id password hashing (intentionally slow). Evaluation is dominated by 90-day daily balance simulation.

---

## 8. Maintenance Procedures

### 8.1 Dependency updates

```bash
# Check outdated packages
pip list --outdated

# Update requirements.txt (test all suites after)
pip install --upgrade <package>
pip freeze > requirements.txt
python -m pytest backend/tests/ buyorwait_engine/tests/ v3/tests/ -q
```

### 8.2 Database cleanup (expired tokens)

Revoked tokens accumulate. Periodic cleanup:
```sql
DELETE FROM revoked_tokens WHERE revoked_at < NOW() - INTERVAL '30 days';
```

### 8.3 Test suite health

Run the full test suite weekly:
```bash
python -m pytest backend/tests/ buyorwait_engine/tests/ v3/tests/ -q --tb=short
```

Expected: **0 failures, 0 errors**.
