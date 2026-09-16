# Production API Runtime & Operations Manual

**Document**: `docs/API_RUNTIME.md`  
**Milestone**: Milestone 5 — Production API Layer  
**Status**: Production Ready & Hardened  
**Date**: September 2026  

---

## 1. Executive Summary & Architecture

The **Buy or Wait? REST API** exposes the underlying financial decision support engine through a versioned (`/api/v1/`), modular, and hardened FastAPI application. It connects client frontends, statement ingestion pipelines, and user profile management to the deterministic V2 solvency core and V3 calibrated empirical risk layer.

```
HTTP Client / Frontend
        │
        ▼
[Security Headers & Observability Middleware]
        │
        ▼
[FastAPI Router: /api/v1/...]
        │
        ▼
[Pydantic v2 Request Validation]
        │
        ▼
[Application Services (DecisionService, IngestionService)]
        │
        ▼
[Tenant-Isolated Repositories (PostgreSQL 16/17)]
        │
        ▼
[Frozen buyorwait_engine (Pure Python Domain Core)]
        │
        ▼
[Pydantic v2 Response DTO / RFC 7807 Error]
```

### Architectural Rules Enforced
1. **Thin Routers**: Routers only handle parameter parsing, dependency injection, and response serialization. Zero financial calculations exist in routers.
2. **Strict Domain Isolation**: No SQLAlchemy ORM models cross the boundary into `buyorwait_engine` or are returned directly to the HTTP client.
3. **No Premature Asynchrony**: The decision engine executes synchronously in <25ms; no Redis queues or background workers are required at this workload scale.

---

## 2. Local Development Quickstart

### Prerequisites
- Python 3.11+
- PostgreSQL 16 or 17 (or local SQLite for lightweight testing)

### Step 1: Start Database
Using Docker Compose:
```bash
docker-compose up -d postgres
```
Or use the local native PostgreSQL 17 service configured on port `5433`:
```bash
& 'C:\Program Files\PostgreSQL\17\bin\postgres.exe' -D 'd:\hacker_rank_projectt\pgdata_test' -p 5433
```

### Step 2: Apply Database Migrations
```bash
# Set database connection string in environment
export DATABASE_URL="postgresql://postgres:postgres@localhost:5433/buyorwait_db"
alembic upgrade head
```

### Step 3: Run FastAPI Application
```bash
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive OpenAPI documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc UI**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

### Step 4: Run Automated API Tests
```bash
python -m unittest discover -s backend/tests/test_api -p "test_*.py" -v
```

---

## 3. Versioned Endpoint Catalog (`/api/v1/...`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/health` | Public | System status, API version, engine version, risk calibration version. |
| `GET` | `/api/v1/profile` | Bearer | Get authenticated user financial profile, balances, and category settings. |
| `PUT` | `/api/v1/profile` | Bearer | Update user financial profile and category preferences. |
| `GET` | `/api/v1/accounts` | Bearer | List active liquid and credit accounts. |
| `GET` | `/api/v1/accounts/{account_id}` | Bearer | Get specific account details (tenant-isolated). |
| `GET` | `/api/v1/transactions` | Bearer | List transactions with date, category filters, and pagination. |
| `POST` | `/api/v1/imports` | Bearer | Upload statement CSV; stages, sanitizes, and returns preview. |
| `GET` | `/api/v1/imports/{import_id}` | Bearer | Get import batch status. |
| `GET` | `/api/v1/imports/{import_id}/preview`| Bearer | Get statement preview with dialect, rows, categories, and warnings. |
| `POST` | `/api/v1/imports/{import_id}/verify` | Bearer | Explicitly commit verified transactions to the permanent ledger. |
| `POST` | `/api/v1/purchases/evaluate` | Bearer | Evaluate purchase proposal with idempotency support. |
| `GET` | `/api/v1/decisions` | Bearer | Get paginated decision history. |
| `GET` | `/api/v1/decisions/{decision_id}` | Bearer | Get decision details with risk breakdown (tenant-isolated). |

---

## 4. Authentication & Tenant Isolation Boundary

1. **Bearer Token Authentication**:
   - All user endpoints require `Authorization: Bearer <token>`.
   - The token resolves to an active `User` in the database.
   - Missing or invalid credentials return `401 Unauthorized` (RFC 7807 format).
   - Inactive or suspended accounts return `403 Forbidden`.
2. **Strict Tenant Scoping**:
   - No endpoint accepts a client-supplied `user_id` query parameter or body attribute to access data.
   - All repositories and services are instantiated with `user_id = current_user.id`.
   - Cross-tenant requests (User A attempting to query User B's resources) return `404 Not Found` to prevent resource enumeration attacks.

---

## 5. Idempotent Purchase Evaluation

To prevent duplicate purchases caused by network retries or double-clicks:

- Clients provide an `X-Idempotency-Key` HTTP header on `POST /api/v1/purchases/evaluate`.
- The server records the request payload hash in `idempotency_records`.
- **Replay Behavior**: If the same user submits the same key with the **identical payload**, the API returns the cached response with `X-Cache: HIT` and `Idempotent-Replay: true`.
- **Conflict Behavior**: If the same user submits the same key with a **different payload**, the API rejects with `409 Conflict` (`"Idempotency key reused with conflicting request payload"`).

---

## 6. RFC 7807 Standardized Error Format

All error responses strictly follow the RFC 7807 Problem Details specification:

```json
{
  "type": "https://api.buyorwait.com/errors/data-insufficient",
  "title": "Data Insufficient",
  "status": 422,
  "detail": "Insufficient verified transaction history (0 verified transactions found, minimum required: 3). Cannot reliably forecast recurring expenses or living burn without guessing.",
  "instance": "/api/v1/purchases/evaluate",
  "code": "DATA_INSUFFICIENT",
  "request_id": "c7a840e6-ec08-410a-b5e1-8cb964893706",
  "error": {
    "code": "DATA_INSUFFICIENT",
    "message": "Insufficient verified transaction history (0 verified transactions found, minimum required: 3). Cannot reliably forecast recurring expenses or living burn without guessing.",
    "affected_data": "transactions",
    "user_action_required": "Import at least 30 to 90 days of verified bank statement history."
  }
}
```

---

## 7. Performance Benchmarks

Measured over 50 consecutive runs on standard test environment:

| Endpoint / Operation | Min Latency | Median P50 | P95 Latency | P99 Latency |
|---|---|---|---|---|
| **Transaction Query** (`GET /transactions?page=1`) | 7.28 ms | **8.42 ms** | 9.82 ms | 31.15 ms |
| **Statement Import & Staging** (`POST /imports`) | 10.19 ms | **11.52 ms** | 20.08 ms | 55.99 ms |
| **Purchase Evaluation** (`POST /purchases/evaluate`) | 20.06 ms | **21.21 ms** | 25.07 ms | 50.63 ms |

Core decision evaluation completes in **~21ms**, well within the 250ms target without requiring Redis or asynchronous queue infrastructure.
