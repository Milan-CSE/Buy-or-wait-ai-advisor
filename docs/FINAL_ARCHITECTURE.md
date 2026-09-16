# Final Architecture — Buy or Wait?

**Architecture Version**: Production V1.0 (Modular Monolith)  
**Status**: COMPLETE AND FROZEN  
**Milestones Completed**: 1 through 8  

---

## 1. Production Request Flow

```
Client (HTTP/HTTPS)
  |
  v
ObservabilityMiddleware          <- Correlation ID assignment, request logging, duration tracking
  |
  v
RateLimitMiddleware              <- Sliding-window per-IP / per-user rate limiting (in-memory)
  |
  v
SecurityHeadersMiddleware        <- CSP, HSTS, X-Frame-Options, Cache-Control: no-store
  |
  v
FastAPI Router                   <- Route dispatch, Pydantic v2 request validation
  |
  v
Depends(get_current_user)        <- JWT HMAC-SHA256 verification, revocation blacklist check
  |                                 Tenant context established: user_id scoped to all queries
  v
Application Service Layer
  |-- IngestionService           <- CSV/OFX parse, magic byte validation, dedup, normalize
  |-- DataQualityEvaluator       <- Completeness, balance coverage, event sufficiency checks
  |-- FinancialStateAdapter      <- DB rows -> FinancialProfileInput + [CashflowEventInput] DTOs
  |-- DecisionService            <- Orchestrates engine call + atomic DB persist
  |
  v
buyorwait_engine (domain-pure, no DB imports)
  |-- BuyOrWaitEngine.evaluate() <- V2 deterministic solvency decision
  |   |-- event_lifecycle        <- settled/pending/scheduled classification + FX resolution
  |   |-- recurrence             <- cadence detection (weekly/bi-weekly/monthly/quarterly)
  |   |-- financial_state        <- H1: daily burn smoothing, H2: income reliability classifier
  |   |-- forecast               <- 90-day daily balance ledger (Decimal precision)
  |   |-- safe_amount            <- Binary search for maximal safe payment
  |   |-- earliest_full_payment  <- H5: objective solvency date scan
  |   |-- spending_optimizer     <- H4: combinatorial adjustable spending changes
  |   |-- candidates             <- full_payment / installments / partial / wait / not_recommended
  |   |-- ranker                 <- Lexicographic candidate selection
  |   `-- V3 RiskEngine          <- P90 stress buffers + risk tier assignment (shadow_audit_only)
  |
  v
DecisionResult (domain DTO)
  |
  v
Atomic DB Persist (single session.commit())
  |-- PurchaseProposal row
  |-- Decision row
  `-- AuditEvent row
  |
  v
ExplanationService               <- Grounded explanation generation (9 invariants enforced)
  |
  v
MetricsCollector.record_decision() <- In-memory Prometheus counters updated
  |
  v
PurchaseEvaluationResponse (Pydantic v2)
  |-- verdict, affordability_status, recommended_payment_method
  |-- amount_safe_to_pay, payment_plan, earliest_date_for_full_payment
  |-- risk_tier, risk_reason, stress_summary
  `-- grounded_explanation (facts + narrative, no invented numbers)
```

---

## 2. Component Inventory

### Domain Engine (`buyorwait_engine/`)
- **Boundary**: Zero database imports. No SQLAlchemy, no psycopg2, no file I/O.
- **Input**: `FinancialProfileInput`, `[CashflowEventInput]`, `PurchaseProposal` — all pure Python dataclasses with `Decimal` monetary fields
- **Output**: `DecisionResult` (includes `risk_assessment: Optional[RiskAssessmentResult]`)
- **Financial precision**: All monetary arithmetic uses Python `Decimal` with `ROUND_HALF_UP`

### Persistence Layer (`backend/database/`)
- **ORM**: SQLAlchemy 2.0 with `Mapped[]` type annotations
- **Models**: `User`, `FinancialProfile`, `BankAccount`, `ImportBatch`, `Transaction`, `PurchaseProposal`, `DecisionRecord`, `AuditEvent`, `IdempotencyRecord`, `RevokedToken`
- **Monetary columns**: `Numeric(18, 4, asdecimal=True)` throughout
- **Tenant isolation**: `TenantScopedRepository` adds `WHERE user_id = :current_user_id` on every query
- **Migrations**: Alembic with 2 versions: `001_initial_schema`, `002_security_hardening`

### Ingestion Layer (`backend/ingestion/`)
- **Parsers**: CSV (stdlib), OFX (regex-based), PDF (structural text extraction)
- **Security**: Magic byte validation (CSV/OFX/PDF), path traversal protection, 10 MB file size limit
- **Quarantine**: Files stored locally; verified transactions persisted to DB
- **Deduplication**: Fingerprint hash on (date, amount, description) prevents duplicate imports

### API Layer (`backend/api/`)
- **Framework**: FastAPI 0.110+ with Pydantic v2
- **Authentication**: Bearer JWT, Argon2id password hashing
- **Idempotency**: `X-Idempotency-Key` header, PostgreSQL-backed `IdempotencyRecord`
- **Error format**: RFC 7807 Problem Details (`application/problem+json`)
- **Endpoints**: 10 routers covering auth, health, profile, accounts, transactions, imports, purchases, decisions

### Security Layer (`backend/api/middleware/`, `backend/auth/`)
- **Rate limiting**: Sliding-window per-IP (auth, upload) and per-user (evaluate, general)
- **Token revocation**: `RevokedToken` table; logout blacklists token immediately
- **Security headers**: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, `Cache-Control: no-store`
- **Cross-tenant protection**: Verified via dedicated test suite (24 security tests)

### Observability Layer (`backend/observability/`)
- **Structured logging**: Single-line JSON to stdout via `JSONLogFormatter`
- **Sensitive data redaction**: JWT tokens, Bearer headers, account numbers, sensitive dict keys
- **Metrics**: In-memory `MetricsCollector`, Prometheus text format at `/api/v1/metrics`
- **Correlation IDs**: `X-Request-ID` assigned per request, propagated through logs

---

## 3. Key Architectural Decisions

### Decision 1: Modular Monolith over Microservices
- **Why**: Moderate scale target (10-50 users). Microservices add operational overhead (network latency, distributed tracing, service discovery) that exceeds value at this scale.
- **When to revisit**: If evaluation requests exceed 100/minute sustained, or if ingestion and evaluation need independent scaling.

### Decision 2: No Redis
- **Why**: Rate limiter is in-memory (sufficient for single instance). Idempotency is PostgreSQL-backed. No message queue needed for synchronous API.
- **When to revisit**: If multiple API instances are deployed simultaneously (distributed rate limiting), or if async job processing is needed.

### Decision 3: No External LLM
- **Why**: Financial explanations use deterministic, grounded templates. Every number in the explanation comes directly from `DecisionResult` fields. LLM hallucination is unacceptable in financial advice.
- **When to revisit**: Evidence parsing (unstructured messages/images) could benefit from structured extraction. Limit to classification tasks, not free-form financial advice generation.

### Decision 4: Decimal Arithmetic Throughout
- **Why**: IEEE 754 float arithmetic introduces rounding drift in financial calculations. `Decimal('0.10') + Decimal('0.20') = Decimal('0.30')` exactly.
- **Impact**: All monetary inputs are validated as `Decimal`. Float inputs are rejected at the domain boundary.

### Decision 5: Shadow Audit Risk Policy (Default)
- **Why**: V3 risk analysis runs in parallel with V2 decision, but does not override V2 output. This allows risk audit without changing proven decision logic.
- **When to revisit**: After sufficient production data confirms risk tier calibration against real user outcomes.

---

## 4. Data Flow Diagram

```
User Financial Data Sources
  |-- CSV bank statements         (upload via /api/v1/imports)
  |-- OFX bank exports            (upload via /api/v1/imports)
  `-- Manual account entry        (POST /api/v1/accounts, /transactions)
                |
                v
         Quarantine (local disk)
                |
                v
         Ingestion Service
         (parse + validate + deduplicate)
                |
                v
         PostgreSQL
         (bank_accounts, transactions, financial_profiles)
                |
                v
         DataQualityEvaluator
         (coverage check, sufficiency check)
                |
           Sufficient? -- No --> DATA_INSUFFICIENT response
                |
               Yes
                |
                v
         FinancialStateAdapter
         (DB rows -> domain DTOs)
                |
                v
         BuyOrWaitEngine.evaluate()
                |
                v
         Atomic persist (proposal + decision + audit)
                |
                v
         ExplanationService
                |
                v
         API Response
```

---

## 5. Test Architecture

| Suite | Location | Count | Type |
|---|---|---|---|
| Backend API + services | `backend/tests/` | 165 | Integration |
| Domain engine contracts | `buyorwait_engine/tests/` | 14 | Unit |
| V3 risk engine | `v3/tests/` | 20 | Unit |
| V2 regression | `code/test_regression.py` | 10 | Regression |
| **Total** | | **~209** | |

All suites run with `python -m pytest` and require zero external services (SQLite in-memory for unit tests).

---

## 6. File Structure

```
hacker_rank_projectt/
|-- buyorwait_engine/         # Domain library (database-agnostic)
|   |-- domain/models.py      # DecisionResult, RiskAssessmentResult, DTOs
|   |-- engine.py             # BuyOrWaitEngine.evaluate()
|   |-- currency/fx.py        # FXEngine (fixed rates)
|   `-- tests/                # 14 unit tests
|
|-- backend/
|   |-- api/
|   |   |-- main.py           # FastAPI app factory
|   |   |-- routers/          # 10 route modules
|   |   |-- schemas/          # Pydantic v2 request/response schemas
|   |   |-- middleware/       # Observability, rate limit, security headers
|   |   |-- config.py         # Settings from environment
|   |   `-- dependencies.py   # Auth injection, DB session
|   |
|   |-- auth/
|   |   |-- password.py       # Argon2id hashing
|   |   `-- jwt_handler.py    # HMAC-SHA256 JWT issue/verify
|   |
|   |-- database/
|   |   |-- session.py        # SQLAlchemy engine + SessionLocal
|   |   |-- models/           # ORM models
|   |   `-- repositories/     # Tenant-scoped query layer
|   |
|   |-- ingestion/
|   |   |-- parsers/          # CSV, OFX, PDF parsers
|   |   |-- service.py        # IngestionService
|   |   `-- quarantine/       # Uploaded files (local disk)
|   |
|   |-- services/
|   |   |-- data_quality.py   # DataQualityEvaluator
|   |   |-- state_adapter.py  # FinancialStateAdapter
|   |   |-- decision_service.py # DecisionService
|   |   `-- explanation_service.py # ExplanationService
|   |
|   |-- observability/
|   |   |-- logger.py         # JSONLogFormatter
|   |   |-- metrics.py        # MetricsCollector
|   |   `-- redactor.py       # PII / secrets redaction
|   |
|   `-- alembic/              # Database migrations
|
|-- v3/                       # V3 statistical risk engine
|   |-- risk_engine/          # stress_buffers, risk_classifier, risk_policy
|   |-- forecasting/          # rolling_mean_8 baseline
|   |-- uncertainty/          # category_empirical P90 quantiles
|   `-- tests/                # 20 unit tests
|
|-- code/                     # V2 competition CLI (frozen)
|-- dataset/                  # Competition dataset files
|-- docs/                     # Architecture, API, deployment docs
|-- Dockerfile                # Multi-stage, non-root (UID 10001)
|-- docker-compose.yml        # PostgreSQL 16 + API service
|-- alembic.ini               # Alembic configuration
|-- requirements.txt          # Pinned Python dependencies
`-- .env.example              # Environment variable template
```
