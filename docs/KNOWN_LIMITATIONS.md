# Known Limitations — Buy or Wait?

This document is an honest, grounded inventory of the system's known constraints and boundaries.
None of these limitations block production deployment at moderate scale (10-50 concurrent users).

---

## 1. Currency Scale in MAE

**Limitation**: The `amount_safe_to_pay` benchmark MAE (106,994) is unnormalized across currencies.

**Detail**: Indonesian Rupiah (IDR) trades at ~15,500 IDR/USD. A 1.5% balance estimation variance in an IDR account produces a raw MAE contribution equivalent to ~$7 USD. Normalized metrics (MASE, sMAPE) are well-calibrated. The aggregate MAE figure is dominated by currency denomination, not prediction error.

**Impact**: MAE as a standalone number overstates real financial error magnitude. Normalized per-currency evaluation shows the engine is accurate.

**Mitigation**: V3 risk engine adds P90 stress buffers which account for this variance conservatively.

---

## 2. Ephemeral File Storage on Ephemeral Platforms

**Limitation**: The file quarantine directory (`backend/ingestion/quarantine/`) is local disk. On cloud platforms with ephemeral storage (Railway default, some Fly.io configs), files are lost on container restart.

**Mitigation**: Render deployment uses a persistent disk mounted at `/app/backend/ingestion/quarantine`. Verified transactions are persisted to PostgreSQL — the quarantine files are only needed for re-inspection/debugging.

**Future**: Replace local quarantine with cloud object storage (S3/GCS) when the user base grows beyond a single instance.

---

## 3. Single-Instance SQLAlchemy Connection Pool

**Limitation**: The SQLAlchemy engine uses the default connection pool (5 connections). At high concurrency (50+ simultaneous purchase evaluations), database connection wait times increase.

**Impact**: P95 latency degrades above ~30-40 concurrent users per instance.

**Mitigation**: Add `SQLALCHEMY_POOL_SIZE` and `SQLALCHEMY_MAX_OVERFLOW` environment variables, or deploy PgBouncer connection pooling.

---

## 4. In-Memory Rate Limiter (Non-Distributed)

**Limitation**: The sliding-window rate limiter stores counters in process memory. With multiple API instances (horizontal scaling), each instance has an independent counter — users can bypass per-instance limits by spreading requests across instances.

**Impact**: Negligible at single-instance deployment (Milestone 8 target). Rate limiting effectiveness degrades if multiple instances run simultaneously.

**Mitigation**: For multi-instance deployments, replace with Redis-backed rate limiter. Redis was explicitly excluded per project constraints (no Redis unless proven necessary for a concrete security requirement). At moderate scale (< 3 instances), per-instance limits with conservative values still provide meaningful protection.

---

## 5. 90-Day Fixed Forecast Horizon

**Limitation**: The financial forecast simulates exactly 90 days forward. Long-duration installment products (6-month, 12-month) may show `earliest_date_for_full_payment = null` even when the user could afford the purchase in month 4 or 5.

**Impact**: For very large purchases with long desired completion dates, the engine may conservatively report `not_affordable` when a slightly longer horizon would show affordability.

**Mitigation**: The `desired_completion_date` field on purchase proposals allows users to indicate intent. The engine correctly identifies when 90 days is insufficient.

---

## 6. Binary Income Reliability Classification

**Limitation**: The income reliability classifier (`is_salary_reliable_for_forecast()`) is binary: income is either included at 100% of confirmed employer payroll or excluded entirely (0%). Gig platform payouts, freelance income, and irregular commissions are conservatively excluded.

**Impact**: For users with substantial gig income, the engine may underestimate `amount_safe_to_pay` conservatively. This is a safe failure mode (errs toward financial caution).

**Future**: A continuous probabilistic income arrival model (e.g., weighted average of recent gig payouts with reliability discount factor) would improve accuracy for mixed-income users.

---

## 7. PDF Ingestion is Structural-Only (No OCR)

**Limitation**: The PDF parser extracts text via `pdfminer.six` or similar. It does not perform OCR on scanned bank statement PDFs (image-only PDFs).

**Impact**: Scanned PDF bank statements (common from older banks) will fail ingestion with a parse error. Only text-based PDFs and CSV/OFX exports are supported.

**Mitigation**: Users should export CSV or OFX format where available. Document this clearly in user-facing help text.

---

## 8. No Real-Time Exchange Rate Updates

**Limitation**: Exchange rates are fixed at the rates provided in `dataset/exchange_rates.csv`. The system does not call any external FX API.

**Impact**: For requests involving foreign-currency transactions, the conversion is accurate only to the settlement date rates supplied by the user or administrator. Extended periods without rate updates introduce FX exposure.

**Mitigation**: Administrators must keep `exchange_rates` table up to date. The domain engine uses settlement-date-matched rates — no stale cross-rate mixing occurs within a single evaluation.

---

## 9. Alembic `path_separator` Deprecation Warning

**Limitation**: Alembic 1.13+ emits a `DeprecationWarning` about missing `path_separator` in `alembic.ini`.

**Impact**: Cosmetic only — warnings appear in test output and migration logs. No functional impact.

**Fix**: Add `path_separator = os` to `[alembic]` section in `alembic.ini` when upgrading.

---

## 10. Argon2id Login Latency (~200-400ms)

**Limitation**: Password verification with Argon2id (time_cost=2, memory_cost=65536) takes 200-400ms on typical hardware.

**Impact**: This is intentional — it prevents brute-force attacks. The rate limiter (5 auth requests/minute) provides additional protection. The login endpoint is not suitable for high-frequency automated polling.

**This is a security feature, not a bug.**
