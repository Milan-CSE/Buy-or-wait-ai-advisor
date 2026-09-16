# Phase 1 Checkpoint: Deterministic Engine Baseline

## 1. Current Benchmark Status (Baseline)
Exact matches: **4 / 25 (16.0%)** (request_01, request_09, request_12, request_16)

Per-field Accuracy:
- `amount_safe_to_pay`: 4 / 25 (16.0%)
- `affordability_status`: 20 / 25 (80.0%)
- `recommended_payment_method`: 22 / 25 (88.0%)
- `payment_plan`: 20 / 25 (80.0%)
- `earliest_date_for_full_payment`: 14 / 25 (56.0%)
- `spending_changes_needed`: 21 / 25 (84.0%)

## 2. Current Implementation Files
All located under `code/`:
- `data_loader.py` — Strict schema typing, Decimal money, date conversions, dataset caching.
- `currency.py` — Exact dated FX lookup on settlement_date.
- `evidence.py` — Structured image evidence manifest (16 verified images) + message evidence patterns.
- `event_lifecycle.py` — Resolution of pending, scheduled, settled, cancelled, failed, non-cash events.
- `recurrence.py` — Categorization and grouping of streams.
- `financial_state.py` — Constructs per-user state (pending debits reserved, fixed & variable recurring, salary projection).
- `forecast.py` — 90-day day-by-day cashflow ledger.
- `safe_amount.py` — Calculation of headroom over 90-day ledger.
- `earliest_full_payment.py` — Earliest date a single full payment keeps 90-day trajectory safe.
- `candidates.py` — Candidate plan generator for all methods.
- `spending_optimizer.py` — Combinatorial search up to 3 legal spending changes.
- `ranker.py` — 6-tier lexicographic ranker and decision constructor.
- `validator.py` — Schema and constraint validation.
- `diagnostics.py` — Per-request audit trace.
- `benchmark.py` — Regression testing on 25 sample requests.
- `main.py` — Full evaluation pipeline runner.

## 3. Current Hypotheses Under Investigation
1. **Salary Projections**: Does ground truth project salary beyond explicit scheduled items when multiple historical events exist, or only when confirmed/scheduled?
2. **Variable Expense Projection**: Currently placing monthly aggregate on the 15th of each month. Is this timing creating artificial dips in balance or misrepresenting safe amount headroom?
3. **Fixed Expense Cadence vs Exact Matching**: Are certain fixed subscriptions being counted multiple times or scheduled on imprecise days?
4. **Specific Failing Cases**:
   - `request_06`: safe_amount 620.40 predicted vs 603.30 truth (17.10 difference matches 19 EUR streaming converted or a specific item).
   - `request_05` and `request_14`: Predicted safe_amount is 0.00 while ground truth is 737 and 597.74 respectively.
   - `request_04`, `request_08`, `request_13`, `request_15`, `request_20`: Predicted safe amount is significantly larger than truth.
