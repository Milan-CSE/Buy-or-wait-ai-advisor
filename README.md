# Buy or Wait? — AI Financial Decision Intelligence System

A production-ready, auditable, risk-aware financial decision system. Given a user's financial profile and a proposed purchase, the system determines whether the purchase is safe, when it becomes safe, and what the optimal payment strategy is.

---

## System Architecture

```
Client (HTTP)
    |
    v
FastAPI API Layer (Authentication, Rate Limiting, Security Headers)
    |
    v
Application Services
    |-- IngestionService  (CSV/OFX/PDF statement parsing)
    |-- DataQualityEvaluator  (completeness + sufficiency checks)
    |-- FinancialStateAdapter  (DB rows -> domain DTOs)
    `-- DecisionService  (orchestration + atomic persistence)
    |
    v
buyorwait_engine  (domain-pure, no DB imports)
    |-- V2 Deterministic Solvency Core (Decimal arithmetic, 90-day ledger)
    `-- V3 Statistical Risk Engine (P90 stress buffers, risk classification)
    |
    v
PostgreSQL  (users, profiles, accounts, transactions, decisions, audit log)
```

**Decision Outputs**: `BUY` / `WAIT` / `SAFER_PAYMENT` / `NOT_RECOMMENDED`

---

## Quick Start

### Requirements
- Python 3.11+
- Docker and Docker Compose (for PostgreSQL)

### Local Development

```bash
git clone <repo-url>
cd hacker_rank_projectt

# Configure environment
cp .env.example .env
# Edit .env: set DATABASE_URL and JWT_SECRET_KEY

# Start PostgreSQL
docker compose up postgres -d

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start API server
uvicorn backend.api.main:app --reload --port 8000
```

### Run with Docker Compose (full stack)

```bash
docker compose up --build
```

API available at: http://localhost:8000

### API Documentation

Interactive API docs: http://localhost:8000/docs

---

## Run Tests

```bash
# Backend API + services (179 tests)
python -m pytest backend/tests/ -q

# Domain engine + V3 risk engine (34 tests)
python -m pytest buyorwait_engine/tests/ v3/tests/ -q

# All tests combined
python -m pytest backend/tests/ buyorwait_engine/tests/ v3/tests/ -q

# V2 competition regression (10 tests)
python code/test_regression.py
```

**Total test count: 213+ tests, all passing.**

---

## Key API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Register new user |
| `POST` | `/api/v1/auth/login` | Authenticate, receive JWT |
| `POST` | `/api/v1/auth/logout` | Revoke current token |
| `GET` | `/api/v1/profile` | Get financial profile |
| `PUT` | `/api/v1/profile` | Update financial profile |
| `POST` | `/api/v1/accounts` | Add bank account |
| `POST` | `/api/v1/imports` | Upload bank statement (CSV/OFX/PDF) |
| `POST` | `/api/v1/purchases/evaluate` | **Evaluate a purchase decision** |
| `GET` | `/api/v1/decisions` | List past decisions |
| `GET` | `/api/v1/decisions/{id}` | Get specific decision |
| `GET` | `/api/v1/health/liveness` | Liveness probe |
| `GET` | `/api/v1/health/readiness` | Readiness probe (DB check) |
| `GET` | `/api/v1/metrics` | Prometheus metrics |

### Example: Evaluate a Purchase

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"YourPassword123!"}' | jq -r .access_token)

# Evaluate purchase
curl -X POST http://localhost:8000/api/v1/purchases/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "item_description": "MacBook Pro",
    "requested_amount": "2499.00",
    "currency": "USD",
    "request_date": "2026-09-15",
    "desired_completion_date": "2026-10-31"
  }'
```

**Response fields:**
- `verdict`: `BUY` / `WAIT` / `SAFER_PAYMENT` / `NOT_RECOMMENDED`
- `amount_safe_to_pay`: Maximum safe payment amount today
- `recommended_payment_method`: `full_payment` / `installments` / `partial_payment` / `wait`
- `payment_plan`: Structured payment schedule (if applicable)
- `earliest_date_for_full_payment`: When full payment becomes safe
- `risk_tier`: `LOW_RISK` / `MODERATE_RISK` / `HIGH_RISK`
- `grounded_explanation`: Deterministic, grounded explanation (no invented numbers)

---

## Decision Engine

### V2 Core (Deterministic)
Built around a pure-Python domain library (`buyorwait_engine/`) with **zero floating-point arithmetic** — all monetary calculations use Python's `Decimal` type:

- **H1: Daily Burn Smoothing** — Variable expenses distributed as daily burn rate
- **H2: Income Reliability** — Only confirmed employer payroll projected as future income
- **H4: Spending Optimizer** — Catalog-minimum spending adjustments
- **H5: Earliest Date Preservation** — Objective solvency date decoupled from deadline
- **90-day daily ledger simulation** with strict minimum balance protection

### V3 Risk Layer (Statistical)
Adds P90 expense stress buffers derived from empirically calibrated category percentiles:

| Category | P90 Stress Factor |
|---|---|
| Groceries | +24.0% |
| Transport | +24.2% |
| Dining | +23.9% |
| Utilities | +12.5% |
| Shopping | +12.6% |
| Fixed expenses | +0.0% |

Default policy: `shadow_audit_only` (V3 runs alongside V2, does not override decisions).

---

## Security Features

- **Argon2id** password hashing (OWASP recommended)
- **HMAC-SHA256 JWT** with configurable secret key
- **Token revocation blacklist** (logout immediately invalidates tokens)
- **Sliding-window rate limiting** on all endpoints
- **CSP, HSTS, X-Frame-Options** security headers
- **Magic byte file validation** (upload security)
- **Path traversal protection** on file operations
- **Cross-tenant isolation** on all database queries

---

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full deployment instructions targeting **Render.com**.

Quick cloud deploy:
1. Push to GitHub
2. Create Render PostgreSQL + Web Service
3. Set environment variables (`DATABASE_URL`, `JWT_SECRET_KEY`, `ENVIRONMENT=production`)
4. Configure persistent disk at `/app/backend/ingestion/quarantine`
5. Set pre-deploy command: `alembic upgrade head`
6. Deploy — health check at `/api/v1/health/liveness` gates traffic

---

## Documentation

| Document | Description |
|---|---|
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Cloud deployment guide (Render) |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operations and failure recovery |
| [docs/FINAL_ARCHITECTURE.md](docs/FINAL_ARCHITECTURE.md) | Complete system architecture |
| [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | Honest limitation inventory |
| [docs/API_SPEC.md](docs/API_SPEC.md) | Full API specification |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Database schema and data model |
| [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md) | Logging, metrics, and monitoring |
| [docs/SECURITY_REQUIREMENTS.md](docs/SECURITY_REQUIREMENTS.md) | Security requirements and controls |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | Final release verification checklist |

---

## Project Status

**FINAL PROJECT STATUS: DEPLOYMENT-READY — MANUAL CLOUD STEP REMAINS**

| Milestone | Status |
|---|---|
| M1: Domain Library Extract | ✅ COMPLETE |
| M2: PostgreSQL Persistence | ✅ COMPLETE |
| M3: Statement Ingestion | ✅ COMPLETE |
| M4: Financial State Adapter | ✅ COMPLETE |
| M5: Production API | ✅ COMPLETE |
| M6: Security Hardening | ✅ COMPLETE |
| M7: Observability + Grounded Explanation | ✅ COMPLETE |
| M8: Final Verification + Deployment | ⚠️ DEPLOYMENT-READY — MANUAL CLOUD STEP REMAINS |

**Version**: v1.0.0  
**Architecture**: Modular Monolith (FastAPI + PostgreSQL + buyorwait_engine)  
**Test Suite**: 213+ tests, all passing
