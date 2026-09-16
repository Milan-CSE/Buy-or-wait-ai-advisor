# Production Financial State Adapter & Decision Service

**Document**: `docs/FINANCIAL_STATE_ADAPTER.md`  
**Milestone**: Milestone 4 — Production Financial State Adapter + Decision Service  
**Status**: Accepted & Hardened  
**Date**: September 2026  

---

## 1. Executive Summary & Architecture Boundary

The **Financial State Adapter and Decision Service** forms the production application-layer bridge connecting persisted user financial statements (`backend/database/`), verified transaction streams (`backend/ingestion/`), and the frozen, database-agnostic domain core (`buyorwait_engine`).

```
┌────────────────────────────────────────────────────────┐
│                   PostgreSQL Database                  │
│  (Profiles, Accounts, Transactions, Decisions, Audits)  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│               Data Quality & Completeness              │
│       DataQualityEvaluator (Checks < 3 tx, > 90d)       │
└───────────────────────────┬────────────────────────────┘
                            │ (If Insufficient -> DATA_INSUFFICIENT)
                            ▼ (If Sufficient)
┌────────────────────────────────────────────────────────┐
│                Financial State Adapter                 │
│   Reconciles Liquid Accounts & Filters Transfers/Unver │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│               buyorwait_engine (Frozen)                │
│    V2 Solvency Engine + V3 Calibrated P90 Stress       │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│              Decision Service Persistence              │
│    Atomic Commit: PurchaseRequest + Decision + Audit   │
└────────────────────────────────────────────────────────┘
```

The domain library `buyorwait_engine` remains 100% pure Python, database-agnostic, and isolated from SQLAlchemy models. No ORM model crosses into the domain layer.

---

## 2. Multi-Account Reconciliation

In real-world financial management, users hold funds and liabilities across disparate institutions and account types. The adapter standardizes and aggregates these positions:

### Liquid Cash Aggregation
- **Eligible Account Types**: `checking`, `savings`, and `cash` with `status = "active"`.
- **Excluded Liabilities**: `credit_card` and loan lines are excluded from available cash balances to prevent artificial solvency inflation.
- **Multi-Currency Normalization**: If an account holds non-home currency (e.g., EUR account for a USD user), the adapter executes dated currency conversion through `FXEngine.to_home(balance, currency, home_currency, as_of_date)`.

---

## 3. Transaction Filtering & Cashflow Classification

Raw statement imports contain noise, adjustments, internal transfers, and unverified data. The adapter applies strict deterministic filters before generating cash-flow event inputs:

1. **Verification Gate**: Only transactions with `confidence_state == "verified"` are admitted. Unverified, pending review, or rejected transactions are completely ignored.
2. **Internal Transfer Defense**: Excludes transfers between user-owned accounts via:
   - Explicit category checks (`category in ('transfer', 'internal_transfer')`).
   - Keyword and regex pattern matching (`InternalTransferDetector`) against user institution names, account types, and masks (e.g., "transfer to savings", "online transfer from checking").
   - This guarantees that moving funds between checking and savings never inflates living expenses or artificial income.
3. **Non-Cash Adjustments**: `cash_type == "non_cash"` and voided records (`cancelled`, `failed`) are excluded.
4. **Lifecycle Mapping**: Remaining transactions are mapped to `CashflowEventInput` via `TransactionMapper.to_domain_dto()`.

---

## 4. Data Quality & Completeness Policy

### Principle: Never Convert Uncertainty into False Precision
If a user's financial picture is partial, broken, or stale, the service does **not** guess living burn, default expenses to zero, or assume unverified income. Instead, it halts evaluation and issues a structured `DATA_INSUFFICIENT` outcome with actionable remediation instructions.

| Trigger Condition | Code | Reason Description | User Action Required |
|---|---|---|---|
| **Missing Profile** | `DATA_INSUFFICIENT` | User financial profile does not exist. | Create financial profile with home currency and reserve target. |
| **Negative Minimum Keep** | `DATA_INSUFFICIENT` | Profile minimum balance to keep cannot be negative. | Update profile with a valid non-negative reserve buffer. |
| **No Active Liquid Accounts** | `DATA_INSUFFICIENT` | No active liquid bank or cash accounts found. | Link at least one active checking, savings, or cash account. |
| **Missing Balance** | `DATA_INSUFFICIENT` | Account balance is null or undefined. | Update account balance to reflect current position. |
| **Unsupported Currency** | `DATA_INSUFFICIENT` | Account or purchase currency cannot be converted to home currency. | Provide exchange rate or convert to supported currency. |
| **Insufficient History** | `DATA_INSUFFICIENT` | Fewer than 3 verified transactions found. | Import at least 30 to 90 days of verified bank statement history. |
| **Stale Balance** | `DATA_INSUFFICIENT` | Latest verified transaction older than 90 days before evaluation date. | Upload recent bank statement reflecting current activity. |

---

## 5. Purchase Proposal Validation

The `PurchaseValidator` enforces strict domain invariants before any financial calculation begins:

- **Amount**: `requested_amount > Decimal("0.00")` (strictly positive Decimal).
- **Currency**: Valid 3-letter ISO code (`^[A-Z]{3}$`).
- **Dates**: Valid ISO dates, `desired_completion_date >= request_date`.
- **Payment Options**: Validated installment counts (`>= 1`), non-negative payment amounts, and financing fees.

---

## 6. Orchestration & Decision Persistence

The `DecisionService` coordinates the full lifecycle:

```python
decision_result = decision_service.evaluate_purchase(
    user_id=user_id,
    purchase_data=proposal_dict_or_dto,
    as_of_date=as_of_date,
    save_to_db=True,
)
```

### Atomic Commit
When `save_to_db=True`, the service commits in a single atomic transaction:
1. `PurchaseRequest` record with user input parameters.
2. `Decision` record with verdict, safe amount, payment plan, risk tier, P50/P90 metrics, and grounded rationale.
3. `AuditEvent` record logging `event_type="purchase_evaluated"` with engine version (`1.0.0`) and calibration version (`v3_empirical_q90_20260914`).
If data quality fails, an immutable audit event `event_type="purchase_evaluation_rejected"` is logged with the exact deficiency reason, and no spurious decision is persisted.

### Exact Reproducibility
Evaluating the identical persisted financial state multiple times yields bit-identical verdicts, safe amounts, and risk metrics.

---

## 7. Verification & Automated Test Suite

The service layer is covered by 23 automated tests in `backend/tests/test_services/`, validated against both SQLite and live PostgreSQL 17:

- `test_data_quality.py` (10 tests): Missing profile, negative balance, no accounts, missing balances, unsupported currencies, insufficient history, unverified transaction exclusion, staleness (> 90 days), and clean data.
- `test_purchase_validator.py` (6 tests): Valid payload, missing amount, non-positive amounts, invalid currency, reverse date order, and payment option parsing.
- `test_state_adapter.py` (3 tests): Multi-account balance aggregation, multi-currency conversion, and internal transfer defense.
- `test_decision_service.py` (4 tests):
  - **Scenario A (BUY)**: Healthy user with surplus cash, verified income -> `BUY` verdict, safe amount persisted, audit event emitted.
  - **Scenario B (WAIT/NOT_RECOMMENDED)**: Tight balance, large purchase -> `WAIT` or `NOT_RECOMMENDED` verdict.
  - **Scenario C (DATA_INSUFFICIENT)**: Missing accounts/transactions -> `DATA_INSUFFICIENT` status, actionable user guidance, rejection audit event emitted.
  - **Exact Reproducibility**: Multiple runs on identical state yield identical decisions.
