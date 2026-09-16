# Production REST API Specification: Buy or Wait?

**Document Version**: 1.0.0  
**Base URL**: `https://api.buyorwait.internal/api/v1`  
**Protocol**: HTTPS / REST / JSON  
**Auth**: Bearer JWT (`Authorization: Bearer <token>`)

---

## 1. Global Request & Response Conventions

### 1.1 Headers
| Header | Description | Mandatory? |
|---|---|:---:|
| `Authorization` | `Bearer <access_token>` | Yes (except `/auth/login`, `/auth/register`) |
| `Content-Type` | `application/json` (or `multipart/form-data` for file uploads) | Yes |
| `X-Correlation-ID` | Client-generated or proxy-generated UUID for end-to-end tracing | Recommended |
| `X-Idempotency-Key` | UUID preventing double execution on mutate endpoints (`/purchases/evaluate`, `/statements/confirm`) | Recommended |

### 1.2 Global Error Model (RFC 7807 Problem Details)
All error responses return `application/problem+json`:
```json
{
  "type": "https://api.buyorwait.internal/errors/insufficient-data",
  "title": "Insufficient Financial Data",
  "status": 422,
  "detail": "User has fewer than 14 days of transaction history. Complete statement import first.",
  "instance": "/api/v1/purchases/evaluate",
  "code": "INSUFFICIENT_HISTORY",
  "invalid_params": [
    {
      "name": "transaction_history",
      "reason": "Minimum 14 days required for variable burn smoothing"
    }
  ]
}
```

---

## 2. Core API Endpoints

### 2.1 Authentication & Profile

#### `POST /auth/login`
Authenticates a user and returns an access and refresh token.
- **Request**:
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```
- **Response (200 OK)**:
```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

---

#### `GET /profile`
Retrieves the user's financial profile, balances, and category settings.
- **Response (200 OK)**:
```json
{
  "user_id": "8a3e7b21-4f12-4c91-b6a3-05c3b991ef21",
  "home_currency": "USD",
  "current_available_balance": "4250.00",
  "minimum_balance_to_keep": "1500.00",
  "protected_categories": ["rent", "debt_repayment", "insurance"],
  "reducible_categories": ["groceries", "dining", "shopping"],
  "stoppable_categories": ["streaming", "gym", "entertainment"],
  "payment_methods_accepted": ["full_payment", "installments", "partial_payment"],
  "max_installment_months": 6,
  "burn_mode": "daily_burn",
  "income_mode": "reliable_only",
  "last_updated": "2026-09-14T10:00:00Z"
}
```

#### `PUT /profile`
Updates financial guardrails and preferences.
- **Request**:
```json
{
  "current_available_balance": "4500.00",
  "minimum_balance_to_keep": "1800.00",
  "protected_categories": ["rent", "healthcare"],
  "reducible_categories": ["groceries", "dining"],
  "stoppable_categories": ["gym", "streaming"],
  "max_installment_months": 6
}
```
- **Response (200 OK)**: Returns updated Profile resource.

---

### 2.2 Statement Import & Ingestion

#### `POST /imports`
Uploads a bank statement (CSV or OFX). Asynchronously parses rows and returns an ingestion job.
- **Content-Type**: `multipart/form-data`
- **Form Data**:
  - `file`: `<binary csv blob>`
  - `account_id`: `UUID` (optional)
  - `currency`: `"USD"`
- **Response (202 Accepted)**:
```json
{
  "import_id": "b1e9c204-1234-4567-89ab-cdef01234567",
  "filename": "checking_statement_aug2026.csv",
  "status": "parsing",
  "poll_url": "/api/v1/statements/b1e9c204-1234-4567-89ab-cdef01234567/status"
}
```

---

#### `GET /imports/{id}/preview`
Returns parsed transactions awaiting user verification before committing to the ledger.
- **Response (200 OK)**:
```json
{
  "import_id": "b1e9c204-1234-4567-89ab-cdef01234567",
  "status": "needs_review",
  "total_rows_parsed": 142,
  "valid_rows": 140,
  "duplicate_rows": 2,
  "inferred_recurring_rules": [
    {
      "category": "salary",
      "average_amount": "3400.00",
      "cadence": "monthly",
      "day_of_month": 15
    },
    {
      "category": "rent",
      "average_amount": "1200.00",
      "cadence": "monthly",
      "day_of_month": 1
    }
  ],
  "sample_transactions": [
    {
      "date": "2026-08-01",
      "raw_description": "ACH DEBIT APARTMENT MGMT RENT",
      "clean_merchant": "Apartment Mgmt",
      "category": "rent",
      "amount": "-1200.00",
      "flexibility": "fixed",
      "is_duplicate": false
    },
    {
      "date": "2026-08-03",
      "raw_description": "WHOLEFDS SFO 1024",
      "clean_merchant": "Whole Foods",
      "category": "groceries",
      "amount": "-142.50",
      "flexibility": "reducible",
      "minimum_allowed_amount": "80.00",
      "is_duplicate": false
    }
  ]
}
```

#### `POST /imports/{id}/verify`
Commits reviewed transactions and confirmed recurring rules to the live financial ledger.
- **Response (200 OK)**:
```json
{
  "import_id": "b1e9c204-1234-4567-89ab-cdef01234567",
  "status": "completed",
  "transactions_imported": 140,
  "recurring_rules_activated": 2
}
```

---

### 2.3 Purchase Evaluation (Core Engine)

#### `POST /purchases/evaluate`
The primary decision endpoint. Evaluates whether a proposed purchase is safe over a 90-day cash-flow forecast.
- **Idempotency**: Supports `X-Idempotency-Key` header.
- **Request**:
```json
{
  "item_description": "Dell XPS 15 Laptop",
  "merchant_name": "Dell Technologies",
  "category": "electronics",
  "requested_amount": "1450.00",
  "currency": "USD",
  "request_date": "2026-09-15",
  "desired_completion_date": "2026-11-15",
  "allows_partial_payment": true,
  "payment_options": [
    {
      "option_code": "upfront",
      "total_payable": "1450.00",
      "down_payment": "1450.00",
      "number_of_installments": 1,
      "installment_amount": "1450.00",
      "cadence": "monthly"
    },
    {
      "option_code": "3_month_zero_apr",
      "total_payable": "1450.00",
      "down_payment": "483.34",
      "number_of_installments": 3,
      "installment_amount": "483.33",
      "cadence": "monthly",
      "apr_percentage": "0.00"
    },
    {
      "option_code": "6_month_affirm",
      "total_payable": "1530.00",
      "down_payment": "255.00",
      "number_of_installments": 6,
      "installment_amount": "255.00",
      "cadence": "monthly",
      "apr_percentage": "12.00"
    }
  ]
}
```

- **Response (200 OK)**:
```json
{
  "decision_id": "d7a4e019-58b2-4c63-912b-319a2e6f4410",
  "request_id": "req_8812a0f1",
  "evaluated_at": "2026-09-15T10:31:00Z",
  "verdict": "SAFER_PAYMENT",
  "amount_safe_to_pay": "620.00",
  "affordability_status": "affordable_with_plan",
  "recommended_payment_method": "installments",
  "recommended_option_code": "3_month_zero_apr",
  "payment_plan": "2026-09-15:483.34|2026-10-15:483.33|2026-11-15:483.33",
  "earliest_date_for_full_payment": "2026-10-01",
  "spending_changes_needed": "none",
  "decision_explanation": "Installment plan (option 3_month_zero_apr) recommended: 3 payments of 483.33 starting 2026-09-15. Total payable: 1450.00. Full payment is not safe today (safe amount: 620.00). Each installment payment is verified safe against your 90-day cashflow forecast while preserving your 1500.00 USD minimum balance.",
  "risk_assessment": {
    "risk_tier": "LOW_RISK",
    "safe_amount_p50": "620.00",
    "safe_amount_p90": "495.00",
    "minimum_balance_p50": "1840.50",
    "minimum_balance_p90": "1610.20",
    "headroom_p50": "340.50",
    "headroom_p90": "110.20",
    "risk_reason": "Robust solvency: user maintains at least 110.20 USD headroom above minimum balance even under 90th-percentile expenditure stress.",
    "stress_summary": "groceries:+24.0%|dining:+23.9%|utilities:+12.5%",
    "p90_breach_detected": false
  },
  "audit_summary": {
    "starting_balance": "4250.00",
    "minimum_balance_to_keep": "1500.00",
    "daily_burn_variable_rate": "38.50",
    "num_candidates_evaluated": 12,
    "forecast_horizon_days": 90
  }
}
```

---

#### `GET /purchases/{id}`
Fetches a previously evaluated purchase, including full candidate evaluations and 90-day daily closing balance projections.
- **Response (200 OK)**:
Returns Decision resource above with extended `daily_ledger`:
```json
{
  "daily_ledger": [
    {
      "day_index": 0,
      "date": "2026-09-15",
      "opening_balance": "4250.00",
      "debits": "-483.34",
      "credits": "0.00",
      "closing_balance_p50": "3766.66",
      "closing_balance_p90": "3757.42",
      "headroom_p50": "2266.66",
      "headroom_p90": "2257.42"
    },
    {
      "day_index": 1,
      "date": "2026-09-16",
      "opening_balance": "3766.66",
      "debits": "-38.50",
      "credits": "0.00",
      "closing_balance_p50": "3728.16",
      "closing_balance_p90": "3709.68",
      "headroom_p50": "2228.16",
      "headroom_p90": "2209.68"
    }
  ]
}
```

---

## 3. Idempotency & Concurrency Specification

1. **Idempotency Window**: 24 hours.
2. **Storage**: PostgreSQL table `idempotency_keys` with SHA-256 payload hash matching and 24-hour TTL.
3. **Execution Flow**:
   - If key does not exist: Acquire lock, process evaluation, store response in Redis with 24h TTL, release lock, return response.
   - If key is currently being processed: Return `409 Conflict` (`"Operation in progress. Retry shortly"`).
   - If key exists with completed response: Return cached HTTP response immediately with header `X-Cache: Idempotent-Hit`.
