# Production Evaluation Plan & Quality Gates: Buy or Wait?

**Document Version**: 1.0.0  
**Phase**: Phase 1 — Production Architecture & Discovery  
**Quality Framework**: Multi-Tier Testing, Solvency Invariants, & Calibration Monitoring

---

## 1. Testing Pyramid & Verification Tiers

```
                       ┌─────────────────────────┐
                       │   Production Telemetry  │ (Shadow runs, post-purchase drift)
                       └────────────┬────────────┘
                                    │
                       ┌────────────┴────────────┐
                       │   Load & Chaos Testing  │ (Locust 50 req/s, DB failure)
                       └────────────┬────────────┘
                                    │
                       ┌────────────┴────────────┐
                       │ Security & Tenant Tests │ (OWASP, RLS cross-tenant audit)
                       └────────────┬────────────┘
                                    │
                       ┌────────────┴────────────┐
                       │ Financial Solvency Gate │ (H1-H5 invariants, 0 unsafe recomms)
                       └────────────┬────────────┘
                                    │
                       ┌────────────┴────────────┐
                       │ Integration Test Suite  │ (FastAPI test client + Testcontainers)
                       └────────────┬────────────┘
                                    │
                       ┌────────────┴────────────┐
                       │    Unit Test Suite      │ (Pure arithmetic, edge cases, Decimal)
                       └─────────────────────────┘
```

---

## 2. Detailed Quality Gates & Acceptance Criteria

### Tier 1: Unit & Numerical Correctness
- **Scope**: `forecast.py`, `safe_amount.py`, `earliest_full_payment.py`, `spending_optimizer.py`, `stress_buffers.py`.
- **Requirements**:
  - Exact `Decimal` arithmetic: 0 floating-point rounding errors.
  - Boundary conditions: $0$ requested amount, amount equals exact starting balance, amount equals exact minimum balance buffer.
  - Date boundaries: Leap year handling (Feb 29), month-end transitions (31st to 30th/28th), year-end boundaries.
  - Negative values: Rejection of negative purchase amounts or negative minimum balance requirements.
- **Pass Criteria**: 100% test pass rate; minimum 95% line coverage on financial modules.

---

### Tier 2: Integration Correctness
- **Scope**: FastAPI endpoints, Pydantic schemas, SQLAlchemy ORM mappings, Redis caching.
- **Tools**: `pytest`, `httpx.AsyncClient`, `testcontainers-python` (ephemeral PostgreSQL & Redis instances).
- **Requirements**:
  - Full request-to-response serialization and contract compliance.
  - Idempotency key verification: identical response returned without re-running engine.
  - Transaction rollbacks on unhandled exceptions.
- **Pass Criteria**: 100% test pass rate.

---

### Tier 3: Financial Decision Correctness & Regression Gate
- **Scope**: Preservation of the validated V2/V3 benchmark.
- **Test Invariants**:
  1. `test_original_pass_cases_preserved`: `request_01`, `request_09`, `request_16` must remain exact PASS.
  2. `test_h1_daily_burn_smoothing`: Variable expenses must be smoothed continuously, avoiding discrete artificial balance dips.
  3. `test_h2_income_reliability`: Unverified platform gig income must be excluded from guaranteed recurring forecast (`request_10` safe amount must equal 0.00).
  4. `test_h4_spending_changes`: Reductions must map strictly to catalog `minimum_allowed_amount`; `wait` and `not_recommended` must have `spending_changes_needed = 'none'`.
  5. `test_h5_earliest_date_scan`: Earliest safe date must reflect objective cash-flow solvency independent of subjective user completion deadline (`request_06` must preserve `2026-01-15`).
  6. `test_v3_p90_monotonicity`: P90 safe amount $\le$ P50 safe amount across all evaluation cases.
- **Pass Criteria**:
  - Public sample benchmark (25 requests): $\ge 96\%$ payment method, $\ge 92\%$ affordability, $\ge 92\%$ plan, $\ge 92\%$ spending changes, $\ge 88\%$ earliest date.
  - Evaluation dataset (250 requests): 0 validation errors, 0 schema violations.

---

### Tier 4: Financial Risk & Safety Invariants (Zero-Tolerance Gates)

| Invariant | Definition | Acceptance Threshold | Failure Action |
|---|---|:---:|---|
| **Unsafe Approval Rate** | System recommends `full_payment` when P50 safe amount < requested amount. | **0.0% (Zero Tolerance)** | **CI Build Breaker & Deployment Abort** |
| **Balance Floor Breach** | Recommended payment plan causes closing balance to fall below `minimum_balance_to_keep` on any day $t \in [0, 90]$. | **0.0% (Zero Tolerance)** | **CI Build Breaker & Deployment Abort** |
| **Plan Cost Conservation** | Sum of tranches in `payment_plan` does not equal `total_payable`. | **0.0% (Zero Tolerance)** | **CI Build Breaker & Deployment Abort** |
| **Illegal Spending Cut** | System recommends stopping or reducing a protected category, or exceeding 3 actions. | **0.0% (Zero Tolerance)** | **CI Build Breaker & Deployment Abort** |
| **False Conservatism Rate** | System recommends `wait` or `not_recommended` on a request where P90 headroom is $\ge 1.5 \times$ requested amount. | **< 2.0%** | Review candidate generation ranking weights. |

---

### Tier 5: Forecast & Risk Calibration

- **Metric**: Empirical Quantile Coverage on out-of-time transaction test data:
  $$\text{Coverage}(q) = \frac{1}{N} \sum_{i=1}^N \mathbb{I}(y_i \le \hat{y}_{i, q})$$
- **Targets for Variable Expense Categories**:
  - P50 Coverage: $50.0\% \pm 3.0\%$
  - P75 Coverage: $75.0\% \pm 3.0\%$
  - P90 Coverage: $90.0\% \pm 2.0\%$ (Target: $\ge 88.0\%$)
- **Underestimation Penalty**:
  Pinball loss on P90: $\mathcal{L}_{0.90}(y, \hat{y}) = \max(0.90(y - \hat{y}), -0.10(y - \hat{y}))$.
- **Cumulative Horizon Safety**: $\ge 95.0\%$ of users experience zero cumulative balance deficit over 90 days under P90 stress.

---

### Tier 6: API Performance & Load Testing

- **Tool**: `locust` executing headless load test scripts against staging environment.
- **Traffic Profile**:
  - Target Concurrency: 50 concurrent simulated users.
  - Target Throughput: 50 evaluations / second sustained for 15 minutes.
- **Service Level Objectives (SLOs)**:
  - `POST /purchases/evaluate`: P50 latency **< 150ms**; P95 latency **< 500ms**; P99 latency **< 1200ms**.
  - `POST /statements/upload` (1,000 rows): P95 processing time **< 3.0s**.
  - HTTP 5xx Error Rate: **< 0.05%**.

---

### Tier 7: Security & Vulnerability Audits

- **Static Analysis (SAST)**:
  - `bandit -r code/ v3/ -ll`: 0 high/medium severity findings.
  - `pip-audit`: 0 known CVEs in installed dependencies.
- **Tenant Isolation Audit**: Automated test suite executing 1,000 randomized cross-tenant requests (User A attempting to query User B's transactions or purchase decisions); must yield 100% `404 Not Found` or `403 Forbidden`.
- **CSV Fuzzing**: Test suite feeding malformed CSVs (null bytes, corrupted delimiters, formula injection payloads, 100MB zip bombs); must yield clean `422 Unprocessable Entity` with zero crashes or unhandled exceptions.

---

## 3. Production Continuous Monitoring & Feedback Loop

1. **Shadow Mode Evaluation**:
   - In production, whenever a user completes an actual purchase or marks an item bought, the system runs the P50 and P90 engine in background shadow mode.
   - If a user who followed a recommendation subsequently breaches their minimum balance, a high-severity alert is emitted to Sentry with the diagnostic audit trace.
2. **Drift Detection**:
   - Monthly scheduled job re-evaluates P90 residual multipliers against newly settled variable expenses.
   - If grocery or dining volatility shifts by $> 5\%$, the system flags stress buffers for recalibration review.
