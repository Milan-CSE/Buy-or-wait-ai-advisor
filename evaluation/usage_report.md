# Token Usage and Cost Report

**Challenge**: HackerRank Orchestrate (September 2026) — Buy or Wait?  
**Run Mode**: Full Dataset Evaluation (dataset/requests.csv, 250 requests)  
**Timestamp**: 2026-09-14  
**Architecture**: V2 Deterministic Solvency Core + V3 Statistical/ML Risk Engine

---

## 1. Summary

| Metric | Value |
|---|---|
| Model Providers | None (Pure Offline Deterministic & Statistical Engine) |
| Model Names | N/A (Statistical time series & scikit-learn offline estimators) |
| Total Model Calls | 0 |
| Total Input Tokens | 0 |
| Total Output Tokens | 0 |
| Total Tokens | 0 |
| Average Input Tokens per Request | 0.0 |
| Average Output Tokens per Request | 0.0 |
| Average Total Tokens per Request | 0.0 |
| Estimated Total Cost (USD) | $0.00 |
| Estimated Cost per Request (USD) | $0.00 |

---

## 2. Details and Execution Profile

- **Requests Processed**: 250 (`request_26` through `request_275`)
- **Execution Time**: ~64.5s (V2 deterministic) / ~200.4s (V3 dual-track P50/P90 shadow evaluation)
- **Engine Components**:
  - Exact-dated foreign exchange rate resolution (`currency.py`)
  - Event lifecycle, pending debit reservation & non-cash handling (`event_lifecycle.py`)
  - Recurring income and expense inference (`recurrence.py`, `financial_state.py`)
  - Daily conservative 90-day cashflow simulation (`forecast.py`)
  - Headroom & safe-amount optimization (`safe_amount.py`, `earliest_full_payment.py`)
  - Multi-plan combinatorial candidate search with legal spending changes (`candidates.py`, `spending_optimizer.py`)
  - Lexicographic candidate ranking & constraint validation (`ranker.py`, `validator.py`)
  - Empirical P90 stress buffers & dual-track solvency risk engine (`v3/risk_engine/`)
  - Controlled integration policies (`shadow_audit_only`, `risk_adaptive`, `conservative_solvency`)
- **API Keys / Credentials Used**: None (fully offline and self-contained).
