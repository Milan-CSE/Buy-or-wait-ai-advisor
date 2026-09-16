# Buy or Wait? — Production Data Model Specification

## 1. Overview & Architectural Goals

The Buy or Wait? production persistence layer is designed to support multi-tenant financial decision intelligence while strictly maintaining domain independence and financial data integrity.

### Core Principles
1. **Multi-Tenant Isolation**: Every financial entity (accounts, transactions, profiles, purchases, decisions) is strictly scoped to a single `user_id`. Tenant boundaries are enforced via foreign keys, composite indexes, and repository-level assertion.
2. **Exact Monetary Representation**: All monetary balances, transaction amounts, and payment plans use `Numeric(18, 4, asdecimal=True)`. Floating-point representations are strictly prohibited across both the schema and the Python application boundary.
3. **Immutable Auditing & Ingestion**: External imports and transaction ledger records are immutable once settled. Mutations require explicit audit events.
4. **Clean Decoupling**: Database models inherit from SQLAlchemy 2.0 declarative base (`Base`) and map to pure, frozen Python domain DTOs (`buyorwait_engine.domain.*`) via explicit mappers.

---

## 2. Entity-Relationship Model

```
                    ┌─────────────────────────┐
                    │          User           │
                    │─────────────────────────│
                    │ id: UUID (PK)           │
                    │ email: VARCHAR (UNIQUE) │
                    │ is_active: BOOLEAN      │
                    │ created_at: TIMESTAMPTZ │
                    └───────────┬─────────────┘
                                │ 1:1
                                ├──────────────────────────┐
                                │ 1:N                      │ 1:N
                    ┌───────────▼─────────────┐ ┌──────────▼──────────┐
                    │    FinancialProfile     │ │     BankAccount     │
                    │─────────────────────────│ │─────────────────────│
                    │ id: UUID (PK)           │ │ id: UUID (PK)       │
                    │ user_id: UUID (FK)      │ │ user_id: UUID (FK)  │
                    │ home_currency: VARCHAR  │ │ institution_name    │
                    │ min_balance: NUMERIC    │ │ account_type        │
                    │ protected_spend: JSONB  │ │ currency: VARCHAR   │
                    │ adjustable_cats: JSONB  │ │ current_balance     │
                    │ payment_prefs: JSONB    │ │ is_active: BOOLEAN  │
                    └─────────────────────────┘ └──────────┬──────────┘
                                                           │ 1:N
                                ┌──────────────────────────┘
                                │ 1:N
                    ┌───────────▼─────────────┐
                    │      Transaction        │
                    │─────────────────────────│
                    │ id: UUID (PK)           │
                    │ user_id: UUID (FK)      │
                    │ account_id: UUID (FK)   │
                    │ date: DATE              │
                    │ amount: NUMERIC(18,4)   │
                    │ currency: VARCHAR       │
                    │ category: VARCHAR       │
                    │ status: VARCHAR         │
                    │ linked_event_id: UUID   │
                    │ transaction_hash: STR   │
                    └───────────▲─────────────┘
                                │ N:1
                    ┌───────────┴─────────────┐
                    │       ImportBatch       │
                    │─────────────────────────│
                    │ id: UUID (PK)           │
                    │ user_id: UUID (FK)      │
                    │ source: VARCHAR         │
                    │ raw_filename: VARCHAR   │
                    │ row_count: INT          │
                    │ imported_at: TIMESTAMPTZ│
                    └─────────────────────────┘

                    ┌─────────────────────────┐
                    │    PurchaseProposal     │
                    │─────────────────────────│
                    │ id: UUID (PK)           │
                    │ user_id: UUID (FK)      │
                    │ item_name: VARCHAR      │
                    │ amount: NUMERIC(18,4)   │
                    │ currency: VARCHAR       │
                    │ target_date: DATE       │
                    │ deadline: DATE          │
                    │ options: JSONB          │
                    └───────────┬─────────────┘
                                │ 1:N
                    ┌───────────▼─────────────┐
                    │     DecisionRecord      │
                    │─────────────────────────│
                    │ id: UUID (PK)           │
                    │ user_id: UUID (FK)      │
                    │ purchase_id: UUID (FK)  │
                    │ recommendation: VARCHAR │
                    │ safe_amount: NUMERIC    │
                    │ payment_plan: JSONB     │
                    │ earliest_date: DATE     │
                    │ spending_changes: JSONB │
                    │ risk_tier: VARCHAR      │
                    │ snapshot_data: JSONB    │
                    └─────────────────────────┘

                    ┌─────────────────────────┐
                    │       AuditEvent        │
                    │─────────────────────────│
                    │ id: BIGSERIAL (PK)      │
                    │ user_id: UUID (FK, opt) │
                    │ event_type: VARCHAR     │
                    │ entity_type: VARCHAR    │
                    │ entity_id: UUID         │
                    │ payload: JSONB          │
                    │ created_at: TIMESTAMPTZ │
                    └─────────────────────────┘
```

---

## 3. Concrete Table Dictionary

### 3.1 `users`
Represents authentication and tenant identity.
- `id` (UUID, Primary Key, default `uuid.uuid4`)
- `email` (VARCHAR(255), Unique, Not Null, Index)
- `hashed_password` (VARCHAR(255), Not Null)
- `full_name` (VARCHAR(255), Nullable)
- `is_active` (BOOLEAN, Default `true`, Not Null)
- `created_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)
- `updated_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)

### 3.2 `financial_profiles`
User financial constraints, priorities, and payment tolerances (1:1 with User).
- `id` (UUID, Primary Key, default `uuid.uuid4`)
- `user_id` (UUID, FK `users.id` ON DELETE CASCADE, Unique, Not Null, Index)
- `home_currency` (VARCHAR(3), Default `'USD'`, Not Null)
- `minimum_balance_to_keep` (NUMERIC(18, 4), Default `0.0000`, Not Null)
- `max_installment_months` (INTEGER, Nullable — NULL indicates user rejects installments)
- `financial_priorities` (JSONB, Default `'[]'`, Not Null)
- `protected_spending_categories` (JSONB, Default `'[]'`, Not Null)
- `adjustable_categories` (JSONB, Default `'[]'`, Not Null)
- `payment_preferences` (JSONB, Default `'[]'`, Not Null)
- `created_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)
- `updated_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)

### 3.3 `bank_accounts`
Physical accounts holding liquid cash balances.
- `id` (UUID, Primary Key, default `uuid.uuid4`)
- `user_id` (UUID, FK `users.id` ON DELETE CASCADE, Not Null, Index)
- `institution_name` (VARCHAR(100), Not Null)
- `account_name` (VARCHAR(100), Not Null)
- `account_type` (VARCHAR(30), Default `'checking'`, Not Null)
- `currency` (VARCHAR(3), Default `'USD'`, Not Null)
- `current_balance` (NUMERIC(18, 4), Default `0.0000`, Not Null)
- `is_active` (BOOLEAN, Default `true`, Not Null)
- `last_synced_at` (TIMESTAMPTZ, Nullable)
- `created_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)
- `updated_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)

### 3.4 `import_batches`
Idempotency and provenance tracking for statement file uploads.
- `id` (UUID, Primary Key, default `uuid.uuid4`)
- `user_id` (UUID, FK `users.id` ON DELETE CASCADE, Not Null, Index)
- `source` (VARCHAR(50), Default `'csv_upload'`, Not Null)
- `raw_filename` (VARCHAR(255), Not Null)
- `file_hash` (VARCHAR(64), Nullable, Index — SHA-256 digest for duplicate upload prevention)
- `row_count` (INTEGER, Default `0`, Not Null)
- `imported_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)

### 3.5 `transactions`
Double-entry / ledger events representing historical, settled, and pending cash flows.
- `id` (UUID, Primary Key, default `uuid.uuid4`)
- `user_id` (UUID, FK `users.id` ON DELETE CASCADE, Not Null, Index)
- `account_id` (UUID, FK `bank_accounts.id` ON DELETE CASCADE, Not Null, Index)
- `batch_id` (UUID, FK `import_batches.id` ON DELETE SET NULL, Nullable, Index)
- `transaction_date` (DATE, Not Null, Index)
- `settlement_date` (DATE, Nullable)
- `amount` (NUMERIC(18, 4), Not Null — Negative for debits/expenses, positive for credits/income)
- `currency` (VARCHAR(3), Default `'USD'`, Not Null)
- `category` (VARCHAR(50), Default `'miscellaneous'`, Not Null, Index)
- `description` (VARCHAR(255), Not Null)
- `counterparty` (VARCHAR(150), Nullable)
- `status` (VARCHAR(20), Default `'settled'`, Not Null — `'settled'`, `'pending'`, `'scheduled'`, `'unrealized'`)
- `is_recurring` (BOOLEAN, Default `false`, Not Null)
- `recurrence_pattern` (VARCHAR(30), Nullable)
- `linked_transaction_id` (UUID, FK `transactions.id` ON DELETE SET NULL, Nullable)
- `transaction_hash` (VARCHAR(64), Nullable, Index — Deduplication hash)
- `created_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)
- `updated_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)

### 3.6 `purchase_proposals`
Customer-submitted requests to evaluate a potential expenditure.
- `id` (UUID, Primary Key, default `uuid.uuid4`)
- `user_id` (UUID, FK `users.id` ON DELETE CASCADE, Not Null, Index)
- `item_name` (VARCHAR(255), Not Null)
- `requested_amount` (NUMERIC(18, 4), Not Null)
- `currency` (VARCHAR(3), Default `'USD'`, Not Null)
- `request_date` (DATE, Not Null)
- `desired_completion_date` (DATE, Nullable)
- `category` (VARCHAR(50), Default `'shopping'`, Not Null)
- `payment_options` (JSONB, Default `'[]'`, Not Null)
- `created_at` (TIMESTAMPTZ, Default `NOW()`, Not Null)

### 3.7 `decision_records`
Immutable decision artifacts generated by `buyorwait_engine`.
- `id` (UUID, Primary Key, default `uuid.uuid4`)
- `user_id` (UUID, FK `users.id` ON DELETE CASCADE, Not Null, Index)
- `purchase_id` (UUID, FK `purchase_proposals.id` ON DELETE CASCADE, Not Null, Index)
- `recommendation` (VARCHAR(30), Not Null — `'buy_now'`, `'wait'`, `'safer_payment'`, `'not_recommended'`)
- `recommended_payment_method` (VARCHAR(30), Not Null — `'full_payment'`, `'partial_payment'`, `'installments'`, `'wait'`, `'not_recommended'`)
- `safe_amount_now` (NUMERIC(18, 4), Default `0.0000`, Not Null)
- `earliest_safer_date` (DATE, Nullable)
- `payment_plan` (JSONB, Default `'[]'`, Not Null)
- `spending_changes` (JSONB, Default `'[]'`, Not Null)
- `risk_tier` (VARCHAR(20), Default `'LOW'`, Not Null — `'LOW'`, `'MODERATE'`, `'HIGH'`)
- `confidence_level` (VARCHAR(20), Default `'HIGH'`, Not Null)
- `explanation` (TEXT, Not Null)
- `headroom_p50` (NUMERIC(18, 4), Nullable)
- `headroom_p90` (NUMERIC(18, 4), Nullable)
- `snapshot_data` (JSONB, Default `'{}'`, Not Null — Verifiable audit snapshot)
- `created_at` (TIMESTAMPTZ, Default `NOW()`, Not Null, Index)

### 3.8 `audit_events`
Append-only system security and compliance log.
- `id` (BIGINT Autoincrement / BIGSERIAL, Primary Key)
- `user_id` (UUID, FK `users.id` ON DELETE SET NULL, Nullable, Index)
- `event_type` (VARCHAR(50), Not Null, Index)
- `entity_type` (VARCHAR(50), Not Null)
- `entity_id` (UUID, Nullable)
- `payload` (JSONB, Default `'{}'`, Not Null)
- `ip_address` (VARCHAR(45), Nullable)
- `created_at` (TIMESTAMPTZ, Default `NOW()`, Not Null, Index)

---

## 4. Invariants Enforced in DB vs. Application

| Invariant | Enforced in Database | Enforced in Application |
|---|---|---|
| User email uniqueness | Unique index `ix_users_email` | Registration validator |
| Exactly one profile per user | Unique index `ix_financial_profiles_user_id` | Profile service assertion |
| Tenant Isolation | Foreign key cascade to `users.id` | `TenantScopedRepository` query filters |
| Monetary Decimal Precision | `NUMERIC(18, 4)` | Python `Decimal` domain type checking |
| Transaction Deduplication | Partial index on `(user_id, transaction_hash)` | Ingestion batch pre-filter |
| Decision Immutability | Restricted DB update grants | Repository omission of `update()` for `DecisionRecord` |
| Minimum balance preservation | Documented in `profiles.minimum_balance_to_keep` | `buyorwait_engine` solvency check |

---

## 5. Performance Indexing Rationale

1. **`ix_transactions_user_date (user_id, transaction_date)`**: The primary engine query retrieves historical and future transactions for a user across a rolling time window. The compound index eliminates table scans.
2. **`ix_transactions_dedup (user_id, transaction_hash)`**: Speeds up duplicate transaction checks during CSV statement ingestion.
3. **`ix_decisions_user_created (user_id, created_at)`**: Powers the user's chronological decision history and timeline in the API.
4. **`ix_audit_events_type_created (event_type, created_at)`**: Optimized for compliance auditing and security review dashboards.
