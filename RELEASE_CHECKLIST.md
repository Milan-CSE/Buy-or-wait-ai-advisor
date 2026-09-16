# Release Checklist — Buy or Wait? v1.0

## Pre-Release Verification

### Test Suite
- [x] Backend tests pass: `python -m pytest backend/tests/ -q` → 165 passed
- [x] Engine tests pass: `python -m pytest buyorwait_engine/tests/ v3/tests/ -q` → 34 passed
- [x] V2 regression: `python code/test_regression.py` → 10/10 passed
- [x] No test failures, no errors
- [x] Total test count: ~209 tests across all suites

### Financial Invariants
- [x] `amount_safe_to_pay` always in [0, requested_amount]
- [x] Balance never drops below `minimum_balance_to_keep` in recommended plan
- [x] Grounded explanation contains no invented numbers (enforced by ExplanationService)
- [x] V3 risk engine in `shadow_audit_only` mode (does not override V2 decisions)
- [x] Currency FX uses settlement-date-matched rates only

### Security
- [x] Argon2id password hashing (not bcrypt, not MD5, not plain)
- [x] HMAC-SHA256 JWT with configurable secret key
- [x] Token revocation blacklist (`revoked_tokens` table)
- [x] Sliding-window rate limiter on auth, evaluate, upload, general endpoints
- [x] Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Cache-Control: no-store
- [x] File upload magic byte validation (CSV/OFX/PDF only)
- [x] Path traversal protection on filenames
- [x] Cross-tenant isolation: all queries scoped to `user_id`
- [x] No secrets in source code or `.env` file (`.env` in `.gitignore`)

### Build and Reproducibility
- [x] Python version: 3.11 (Dockerfile uses `python:3.11-slim`)
- [x] Dependencies: `requirements.txt` with version constraints
- [x] Docker multi-stage build verified (builder → runner)
- [x] Non-root user: `appuser` (UID 10001)
- [x] `docker compose up --build` succeeds
- [x] Alembic migration from empty DB: `alembic downgrade base && alembic upgrade head` succeeds
- [x] All 11 expected tables created after migration

### Documentation
- [x] `README.md` updated with production API instructions
- [x] `docs/DEPLOYMENT.md` with Render deployment steps
- [x] `docs/RUNBOOK.md` with operational procedures
- [x] `docs/FINAL_ARCHITECTURE.md` with complete system architecture
- [x] `docs/KNOWN_LIMITATIONS.md` with honest limitation inventory
- [x] `evaluation/usage_report.md` with token usage summary (if LLM used)
- [x] `docs/API_SPEC.md` with endpoint documentation

### Cleanup
- [x] No scratch files in repository root
- [x] No `__pycache__` in source control (`.gitignore` covers)
- [x] No temporary database files committed (`.db` files in `.gitignore`)
- [x] No API keys or secrets in any committed file
- [x] `.env.example` has placeholder values only

### Deployment
- [x] Cloud platform selected: Render.com (rationale in `docs/DEPLOYMENT.md`)
- [x] Persistent disk configured for file quarantine
- [x] Pre-deploy migration command: `alembic upgrade head`
- [x] Health check path: `/api/v1/health/liveness`
- [x] All required environment variables documented

---

## Release Sign-Off

| Milestone | Status |
|---|---|
| M1: Domain Library Extract | COMPLETE |
| M2: PostgreSQL Persistence | COMPLETE |
| M3: Statement Ingestion | COMPLETE |
| M4: Financial State Adapter | COMPLETE |
| M5: Production API | COMPLETE |
| M6: Security Hardening | COMPLETE |
| M7: Observability + Grounded Explanation | COMPLETE |
| M8: Final Verification + Deployment | DEPLOYMENT-READY — MANUAL CLOUD STEP REMAINS |

**FINAL PROJECT STATUS: DEPLOYMENT-READY — MANUAL CLOUD STEP REMAINS**

Version: v1.0.0  
Date: 2026-09-15  
Architecture: Modular Monolith (FastAPI + PostgreSQL + buyorwait_engine)
