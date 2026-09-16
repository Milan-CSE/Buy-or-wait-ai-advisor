# Technical Architecture Specification: Buy or Wait?

**Document Version**: 1.0.0  
**Phase**: Phase 1 — Production Architecture & Discovery  
**Architecture Style**: Modular Monolith (Python / FastAPI / PostgreSQL / Redis)  
**Deployment Target**: Moderate-scale Cloud / Containerized Environment (AWS / GCP / Bare Metal)

---

## 1. Architectural Philosophy & Guiding Principles

1. **Modular Monolith First**: A single well-structured deployable service eliminates network hops, distributed transactions, and microservice orchestration overhead while fully satisfying moderate scale (10,000–50,000 active users, 50 req/s peak).
2. **Deterministic Financial Calculation**: All monetary math is executed using Python's arbitrary-precision `Decimal` type. Floating-point types (`float`, `double`) are strictly prohibited in the financial core.
3. **Strict Separation of Calculation vs. Language**: Machine learning models and Large Language Models (LLMs) are **never** calculation authorities. Solvency constraints and ledger math belong exclusively to the deterministic V2/V3 engine.
4. **Stateless Core Engine with Reusable Domain Logic**: The existing `code/` and `v3/` modules are retained as a pure, dependency-isolated Python library (`buyorwait_engine`) invoked by the application layer.
5. **Auditable & Reproducible State**: Every recommendation can be deterministically replayed and verified given the user's balance sheet snapshot as of the request date.

---

## 2. End-to-End System Architecture

```
                                [Client Applications]
                        (Next.js Web App / React Native Mobile)
                                          │
                                     HTTPS / WSS
                                          │
                                          ▼
                       ┌─────────────────────────────────────┐
                       │   Reverse Proxy & TLS Termination   │
                       │          (Nginx / Cloudflare)       │
                       │  - Rate Limiting, DDoS Mitigation   │
                       └─────────────────────────────────────┘
                                          │
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              MODULAR MONOLITH BACKEND                                  │
│                                  (FastAPI / Python 3.14)                               │
│                                                                                        │
│  ┌───────────────────────────┐  ┌───────────────────────────┐  ┌────────────────────┐  │
│  │   Auth & Security Module  │  │  Purchase Decision API    │  │ Ingestion Pipeline │  │
│  │  - JWT Bearer Auth        │  │  - POST /purchases/eval   │  │ - CSV File Upload  │  │
│  │  - Tenant / User Scope    │  │  - GET  /purchases/{id}   │  │ - Normalization    │  │
│  └───────────────────────────┘  └───────────────────────────┘  └────────────────────┘  │
│                │                              │                           │            │
│                ▼                              ▼                           ▼            │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              APPLICATION CORE LAYER                              │  │
│  │                                                                                  │  │
│  │  ┌─────────────────────────────────┐      ┌───────────────────────────────────┐  │  │
│  │  │    Ingestion & Dedup Service    │      │    Profile & Statement Service    │  │  │
│  │  │ - CSV schema detector           │      │ - Balance sheet reconciliation    │  │  │
│  │  │ - Transaction hash deduplicator │      │ - Category preference manager     │  │  │
│  │  │ - Cadence inference trigger     │      │ - Message evidence amendment store│  │  │
│  │  └─────────────────────────────────┘      └───────────────────────────────────┘  │  │
│  │                     │                                        │                   │  │
│  │                     └───────────────────┬────────────────────┘                   │  │
│  │                                         ▼                                        │  │
│  │  ┌────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │                         STATE ADAPTER LAYER                                │  │  │
│  │  │ - Maps DB entities (Transactions, Profiles) to Engine Domain Objects       │  │  │
│  │  │   (`FinancialProfile`, `FinancialState`, `ScheduledItem`, `Request`)       │  │  │
│  │  └────────────────────────────────────────────────────────────────────────────┘  │  │
│  │                                         │                                        │  │
│  │                                         ▼                                        │  │
│  │  ┌────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │                   BUY OR WAIT? CORE FINANCIAL ENGINE                       │  │  │
│  │  │                          (Reusable V2 + V3)                                │  │  │
│  │  │                                                                            │  │  │
│  │  │   ┌───────────────────────────────┐     ┌──────────────────────────────┐   │  │  │
│  │  │   │  V2 Deterministic Solvency    │     │      V3 Risk Engine          │   │  │  │
│  │  │   │ - 90-day daily cashflow ledger│     │ - Validated P90 multipliers  │   │  │  │
│  │  │   │ - Binary search safe amount   │ ──► │ - Stressed ledger simulation │   │  │  │
│  │  │   │ - Earliest payment date scan  │     │ - Headroom & breach eval     │   │  │  │
│  │  │   │ - Combinatorial spending cuts │     │ - Risk tier classification   │   │  │  │
│  │  │   │ - Lexicographical plan ranker │     │ - Stress summary generator   │   │  │  │
│  │  │   └───────────────────────────────┘     └──────────────────────────────┘   │  │  │
│  │  └────────────────────────────────────────────────────────────────────────────┘  │  │
│  │                                         │                                        │  │
│  │                                         ▼                                        │  │
│  │  ┌────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │                         EXPLANATION SERVICE                                │  │  │
│  │  │ - Primary: Grounded deterministic template generator                       │  │  │
│  │  │ - Optional: LLM phrasing layer (Strict Guardrail: No calculation access)   │  │  │
│  │  └────────────────────────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
          │                                  │                               │
          ▼                                  ▼                               ▼
┌──────────────────┐               ┌──────────────────┐            ┌──────────────────┐
│  PostgreSQL 16   │               │     Redis 7      │            │  Object Storage  │
│  (ACID Store)    │               │ (Cache & Queue)  │            │   (S3 / MinIO)   │
│ - Users          │               │ - Session tokens │            │ - Raw Statement  │
│ - Profiles       │               │ - Rate limits    │            │   CSV / OFX      │
│ - Transactions   │               │ - Ingestion queue│            │   files          │
│ - Purchases/Decs │               │ - Forecast cache │            │ - Receipt Images │
│ - Audit Ledger   │               │                  │            │                  │
└──────────────────┘               └──────────────────┘            └──────────────────┘
```

---

## 3. Mapping Existing V2/V3 Modules to Production Layers

| Production Layer | Existing Module(s) | Reusability Status | Modifications / Production Wrap Needed |
|---|---|---|---|
| **Data Ingestion & Import** | `code/data_loader.py` | Partial (30%) | Replace static CSV file loading with multipart file upload, CSV dialect detection, and database-backed ingestion models. |
| **Transaction Lifecycle** | `code/event_lifecycle.py` | High (95%) | Reused directly. Classifies transactions into `IMMEDIATE_DEBIT`, `FUTURE_DEBIT`, `SETTLED_INCOME`, `CONFIRMED_INCOME`, `NON_CASH`, and reserves pending debits. |
| **Recurrence Detection** | `code/recurrence.py` | High (90%) | Reused directly. Analyzes transaction cadence (weekly, bi-weekly, monthly) to project future recurring burn. |
| **Currency & FX** | `code/currency.py` | Medium (70%) | Replace static `dataset/exchange_rates.csv` lookup with database table storing daily central bank / ECB exchange rate feeds, cached in Redis. |
| **Financial State Construction** | `code/financial_state.py` | High (95%) | Reused directly. Generates 90-day baseline state using daily burn variable smoothing (H1) and income reliability filtering (H2). |
| **Daily Ledger Simulation** | `code/forecast.py` | Complete (100%) | Reused as-is. Pure arithmetic daily closing ledger maintaining `minimum_balance_to_keep`. |
| **Safe Amount Computation** | `code/safe_amount.py` | Complete (100%) | Reused as-is. Binary search optimization over 90-day cashflow headroom. |
| **Earliest Date Scan** | `code/earliest_full_payment.py` | Complete (100%) | Reused as-is. Scans first calendar date where full purchase is solvent. |
| **Spending Optimization** | `code/spending_optimizer.py` | Complete (100%) | Reused as-is. Combinatorial search for up to 3 legal spending adjustments on reducible/stoppable categories. |
| **Candidate Generation & Ranking** | `code/candidates.py`, `code/ranker.py` | Complete (100%) | Reused as-is. Compares full payment, installments, partial payment, and wait options. |
| **Output Contract & Validation** | `code/validator.py` | High (90%) | Replaced/wrapped by Pydantic v2 response validation models for API serialization. |
| **Statistical Forecasting Baseline** | `v3/forecasting/baselines.py` | Complete (100%) | `rolling_mean_8` used as the production expected point forecast. |
| **Empirical Uncertainty Buffers** | `v3/risk_engine/stress_buffers.py` | Complete (100%) | Reused as-is. Applies category-specific P90 stress multipliers to variable debits. |
| **Solvency Risk Classifier** | `v3/risk_engine/risk_classifier.py` | Complete (100%) | Reused as-is. Evaluates P50 vs P90 headroom; classifies into `LOW_RISK`, `MODERATE_RISK`, `HIGH_RISK`. |
| **Shadow / Risk Policies** | `v3/risk_engine/risk_policy.py` | Complete (100%) | Reused as-is. Enforces `shadow_audit_only` (default) or configurable `risk_adaptive` guardrails. |
| **Orchestration Layer** | `code/main_v3.py` | Medium (75%) | Reusable orchestration logic encapsulated into a Python service class `PurchaseDecisionService`. |

---

## 4. Detailed Component Design

### 4.1 Web & API Layer (FastAPI)
- **Framework**: FastAPI with Python 3.14 (async I/O for network calls; CPU-bound financial calculations run in threadpool via `anyio.to_thread.run_sync` to keep the event loop unblocked).
- **Serialization**: Pydantic v2 for strict type checking, JSON schema validation, and automatic OpenAPI 3.1 documentation.
- **Routing Structure**:
  - `/api/v1/auth`: Authentication, registration, token refresh.
  - `/api/v1/profile`: Financial profile management (currency, balances, category rules).
  - `/api/v1/statements`: Statement upload, parsing, review, and transaction reconciliation.
  - `/api/v1/transactions`: Manual transaction CRUD and category tagging.
  - `/api/v1/purchases`: Purchase request evaluation, candidate inspection, decision history.
  - `/api/v1/health`: Liveness and readiness probes for orchestrators.

### 4.2 Database Architecture (PostgreSQL 16)
- **Engine**: PostgreSQL 16 with UUID primary keys and JSONB fields for audit ledgers.
- **Connection Management**: Asyncpg with SQLAlchemy 2.0 (async ORM) and PgBouncer connection pooling.
- **Tenancy**: Row-Level Tenancy. Every table contains `user_id` indexed with a composite B-tree index `(user_id, created_at)` or `(user_id, transaction_date)`.
- **Migration Engine**: Alembic for versioned, reproducible schema migrations.
- **Key Tables**:
  - `users`: Authentication credentials, email, password hash, status.
  - `financial_profiles`: Current liquid balance, emergency buffer, currency, protected/flexible category arrays.
  - `imported_files`: File upload metadata, S3 storage URI, ingestion status, parse error log.
  - `transactions`: Historical and scheduled financial events with lifecycle status, category, amount, flexibility.
  - `recurring_rules`: Inferred or manually confirmed recurring streams (salary, rent, utility burn).
  - `purchase_requests`: Proposed purchases with amount, deadline, financing options.
  - `decisions`: Evaluation outcomes, safe amounts, selected payment plans, risk profiles, full 90-day simulation ledgers.
  - `audit_logs`: Append-only record of all balance changes, rule edits, and decisions.

### 4.3 Cache & Asynchronous Processing (Redis 7)
- **Engine**: Redis 7.
- **Use Cases**:
  1. **Session & Rate Limiting**: Distributed token bucket rate limiting (e.g., 60 req/min for evaluations; 5 uploads/hour for statements).
  2. **Exchange Rate Cache**: Daily FX rates cached with 24-hour TTL (`fx:{from}:{to}:{date}`).
  3. **Background Job Queue**: Worker queue (using ARQ or Celery) for parsing large CSV/OFX statements (>10,000 rows) and computing cadence inferences asynchronously without blocking HTTP requests.
  4. **Idempotency Locks**: Redlock on `(user_id, request_id)` to prevent duplicate concurrent purchase simulations.

### 4.4 Object Storage (S3 / MinIO)
- **Engine**: AWS S3 (or MinIO for local development / on-premise deployments).
- **Bucket Layout**:
  - `statements/{user_id}/{file_uuid}.csv`: Encrypted original user bank statement uploads.
  - `receipts/{user_id}/{file_uuid}.png`: Optional receipt / invoice images.
- **Security**: Server-Side Encryption (SSE-S3 or SSE-KMS), private ACLs only, short-lived signed URLs for upload/download.

---

## 5. The AI & LLM Operational Boundary

A critical requirement of financial reliability is ensuring that generative models never perform numerical decisioning.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STRICT AI / LLM BOUNDARY                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ ALLOWED USES FOR LLM:                                                       │
│ 1. Transaction Description Normalization:                                   │
│    - Raw string "SQ *BLUE BOTTLE COFFEE SAN FRAN CA"                        │
│      ──► Normalized Merchant: "Blue Bottle Coffee", Category: "dining"      │
│ 2. Unstructured Message / Receipt Parsing:                                 │
│    - Extracting proposed installment terms from pasted seller text          │
│ 3. Natural Language Explanation Formatting:                                 │
│    - Translating the deterministic output into empathetic, clear English    │
│    - Strict Guardrail: Must use ONLY the variables present in the           │
│      engine decision payload (amounts, dates, categories, risk tier).       │
│                                                                             │
│ STRICTLY FORBIDDEN FOR LLM:                                                 │
│ ❌ Calculating balances, headroom, or safe amounts.                         │
│ ❌ Deciding whether a purchase is affordable or safe.                       │
│ ❌ Recommending payment options not generated by the engine.                │
│ ❌ Altering installment dates, amounts, or fee structures.                  │
│ ❌ Overriding user minimum balance constraints.                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Prompt Guardrail Pipeline
When the LLM is invoked to generate the user-facing explanation:
1. Input: Exact JSON from `Decision` + `RiskProfile`.
2. System Instruction: *"You are an explanation translator for a deterministic financial engine. You must explain the decision using ONLY the provided facts. Never perform math. Never state an amount or date not in the input."*
3. Output Validation: A regex and token-validator verifies that any monetary figure (`$X.YY`) or date (`YYYY-MM-DD`) in the LLM response exists verbatim in the engine payload. If a hallucination is detected, the system immediately falls back to the deterministic template explanation.

---

## 6. Observability, Logging, & Operations

### 6.1 Structured Logging & Correlation
- **Format**: JSON structured logging (Loguru / structlog).
- **Mandatory Correlation IDs**: Every request receives an `X-Correlation-ID` header propagated across FastAPI handlers, engine runs, and database queries.
- **PII / Financial Redaction**: Zero logging of account numbers, full names, or auth tokens. Monetary figures logged with tenant context only.

### 6.2 Metrics & Telemetry (Prometheus / OpenTelemetry)
- `engine_evaluation_duration_seconds`: Histogram of simulation latency (p50, p95, p99).
- `engine_decisions_total{verdict="buy|wait|safer_payment|not_recommended"}`: Counter tracking recommendations.
- `engine_risk_tier_total{tier="low|moderate|high"}`: Counter tracking risk distributions.
- `statement_ingestion_seconds`: Histogram of statement parse and processing time.
- `statement_parse_errors_total{reason="..."}`: Counter tracking upload formatting failures.

### 6.3 Error Tracking
- Sentry integration capturing unhandled exceptions with full stack traces, correlation IDs, and non-sensitive request parameters.

---

## 7. CI/CD & Deployment Architecture

- **Containerization**: Multi-stage Docker build producing a minimal Python 3.14 slim image (<200MB).
- **Local Development**: `docker-compose.yml` spinning up FastAPI service, PostgreSQL 16, Redis 7, and MinIO.
- **CI Pipeline (GitHub Actions)**:
  1. Linting & Formatting: `ruff check`, `ruff format --check`, `mypy --strict`.
  2. V2 Deterministic Regression Suite: `code/test_regression.py` (must be 100% PASS).
  3. V3 Risk & Integration Suite: `v3/tests/` (must be 100% PASS).
  4. API Contract & Security Tests: Pytest suite testing authentication, authorization, and rate limiting.
  5. Deterministic Benchmark Verification: Automated check asserting benchmark accuracy does not regress.
- **Production Deployment**: Container service (AWS ECS Fargate, GCP Cloud Run, or Kubernetes) running with health checks, horizontal autoscaling (min 2 instances), and automated database backups.
