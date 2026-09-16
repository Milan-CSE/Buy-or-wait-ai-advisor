# Buy or Wait? — AI Financial Decision Intelligence Engine (V2)

An auditable, risk-aware financial decision intelligence system designed for the **HackerRank Orchestrate** challenge (*Buy or Wait?*). The system evaluates real-world purchase requests against reconstructed personal balance sheets, multi-currency cash flows, recurring commitments, flexible spending categories, and supporting evidence messages to recommend optimal, safe payment actions.

---

## 1. System Architecture

The engine is built around a deterministic, high-precision financial core using Python's `Decimal` arithmetic to eliminate floating-point drift. It operates across modular stages:

```
[Dataset Files]
       │
       ▼
┌───────────────────┐     ┌───────────────────────┐
│  data_loader.py   │ ──► │  event_lifecycle.py   │ (Resolves settled, pending, scheduled,
└───────────────────┘     └───────────────────────┘  and reserves unconfirmed credits)
       │                              │
       ▼                              ▼
┌───────────────────┐     ┌───────────────────────┐
│   recurrence.py   │ ──► │  financial_state.py   │ (H1: Daily Burn Variable Smoothing
└───────────────────┘     └───────────────────────┘  H2: Income Reliability Classifier)
                                      │
                                      ▼
                          ┌───────────────────────┐
                          │      forecast.py      │ (90-day daily balance simulation
                          └───────────────────────┘  preserving minimum_balance_to_keep)
                                      │
                 ┌────────────────────┴────────────────────┐
                 ▼                                         ▼
     ┌───────────────────────┐                 ┌───────────────────────┐
     │    safe_amount.py     │                 │earliest_full_payment  │ (H5: Solvency date scan
     └───────────────────────┘                 └───────────────────────┘  without suppression)
                 │                                         │
                 └────────────────────┬────────────────────┘
                                      │
                                      ▼
                          ┌───────────────────────┐
                          │ spending_optimizer.py │ (H4: Combinatorial adjustments using
                          └───────────────────────┘  catalog minimum_allowed_amount)
                                      │
                                      ▼
                          ┌───────────────────────┐
                          │     candidates.py     │ (Generates full, installment, partial,
                          └───────────────────────┘  wait, and decline payment candidates)
                                      │
                                      ▼
                          ┌───────────────────────┐
                          │       ranker.py       │ (Selects best candidate; enforces
                          └───────────────────────┘  H4 'none' rules & H5 date preservation)
                                      │
                                      ▼
                          ┌───────────────────────┐
                          │     validator.py      │ (Strict domain schema validation)
                          └───────────────────────┘
                                      │
                                      ▼
                                [output.csv]
```

### Module Responsibilities
- **`data_loader.py`**: Ingests profiles, historical transactions, fixed exchange rates, seller payment options, and evidence messages.
- **`event_lifecycle.py`**: Classifies transaction states (`settled`, `pending`, `scheduled`, `unrealized`); holds pending debits in reserve and rejects unconfirmed credits.
- **`recurrence.py`**: Analyzes transaction cadences and intervals (weekly, bi-weekly, monthly, quarterly).
- **`financial_state.py`**: Reconstructs complete financial position over a 90-day horizon:
  - **Daily Burn Variable Smoothing (H1)**: Spreads variable recurring expenses continuously across the forecast to avoid artificial ledger drops.
  - **Income Reliability Classifier (H2)**: Enforces strict criteria to ensure only confirmed salary and regular employer payroll are projected into future cash flows.
- **`forecast.py`**: Generates daily closing ledger balances while strictly protecting the user's `minimum_balance_to_keep`.
- **`safe_amount.py`**: Determines the maximal safe immediate expenditure on `request_date` via binary search over 90-day solvency constraints.
- **`earliest_full_payment.py`**: Identifies the earliest calendar date on which the full purchase can be paid in one lump sum while preserving downstream solvency.
- **`spending_optimizer.py`**: Finds valid spending modifications (`stop`, `reduce_to`) on flexible categories, mapping reductions to original catalog minimums (H4).
- **`candidates.py`**: Forms candidate actions (`full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`).
- **`ranker.py`**: Evaluates candidates by feasibility, completion deadline, user payment preferences, interest/total cost, and payment count.
- **`validator.py`**: Enforces all submission constraints, bounds, and string formats.

---

## 2. Research & Hypothesis Progression (V1 to V2)

### V1 Baseline
The initial submission delivered strong categorical accuracy (88% payment method, 88% affordability), but suffered from an `amount_safe_to_pay` Mean Absolute Error (MAE) of **190,594.67** due to discrete variable expense clustering and unverified platform gig income.

### H1: Variable Expense Timing (ACCEPTED)
- **Investigation**: In V1, recurring variable expenses were placed on discrete projected dates, creating artificial cash-flow dips that artificially depressed `amount_safe_to_pay`.
- **Implementation**: Converted variable recurring expenses to an empirical daily burn rate based on observed cadence.
- **Outcome**: Slashed MAE from 190,594.67 to 116,646.04 (-38.8%) with zero categorical regressions.

### H2: Income Reliability Classification (ACCEPTED)
- **Investigation**: In `request_10`, variable gig platform payouts (*"Delivery platform payout"*) were projected as guaranteed recurring income, creating an unsafe overestimate of 254,000 INR.
- **Implementation**: Introduced `is_salary_reliable_for_forecast()` in `financial_state.py` to require verified employer payroll or explicit scheduling before projecting future income.
- **Outcome**: Reduced `request_10` safe amount error by 95% (from 254,000 INR to 12,700 INR) and reduced benchmark MAE from 116,646.04 to **106,994.04** with zero regressions.

### H3: Expense Forecasting Cadence & Amount Adjustments (REJECTED)
- **Investigation**: Traced top remaining safe-amount errors (`request_04`, `request_25`, `request_02`).
- **Findings**: 99% of raw unweighted MAE was driven by Indonesian Rupiah currency scale (~15,500 IDR/USD, representing ~1.5% balance variance). Tested 6 alternative estimators (lookback windows, robust medians/means, empirical spending). All alternatives degraded MAE (+11% to +80%) or caused regressions.
- **Decision**: Empirically rejected to preserve generalized accuracy.

### H4: Spending-Change Decision Optimization (ACCEPTED)
- **Investigation**: Addressed 5 spending-change mismatches. Discovered that (1) `reduce_to` targets were picking up daily-burn scaled amounts instead of catalog minimums, and (2) `wait` and `not_recommended` decisions were prescribing spending cuts.
- **Implementation**: Mapped `reduce_to` values to original catalog `minimum_allowed_amount` from lifecycle events, and enforced `spending_changes_needed = 'none'` for non-proceed decisions.
- **Outcome**: Increased `spending_changes_needed` accuracy from 20/25 (80.0%) to **23/25 (92.0%)**.

### H5: Earliest Full-Payment Date Preservation (ACCEPTED)
- **Investigation**: `ranker.py` artificially wiped `edfp = None` whenever a request missed the user's completion deadline (`not_affordable`), violating the challenge spec where `earliest_date_for_full_payment` is an objective measure of financial solvency.
- **Implementation**: Preserved `earliest_full_date` across all non-`affordable_now` outcomes in `ranker.py`.
- **Outcome**: Corrected `request_06` (`2026-01-15`), increasing earliest date accuracy from 21/25 (84.0%) to **22/25 (88.0%)** with zero regressions.

---

## 3. Benchmark Comparison (25 Public Sample Requests)

| Evaluation Field | V1 Baseline | V2 Final | Improvement |
| :--- | :---: | :---: | :---: |
| **`recommended_payment_method`** | 22 / 25 (88.0%) | **24 / 25 (96.0%)** | **+8.0%** |
| **`affordability_status`** | 22 / 25 (88.0%) | **23 / 25 (92.0%)** | **+4.0%** |
| **`payment_plan`** | 22 / 25 (88.0%) | **23 / 25 (92.0%)** | **+4.0%** |
| **`spending_changes_needed`** | 19 / 25 (76.0%) | **23 / 25 (92.0%)** | **+16.0%** |
| **`earliest_date_for_full_payment`** | 21 / 25 (84.0%) | **22 / 25 (88.0%)** | **+4.0%** |
| **`amount_safe_to_pay` MAE** | 190,594.67 | **106,994.04** | **-43.9%** |
| **Exact 7-field Matches** | 2 / 25 (8.0%) | **3 / 25 (12.0%)** | **+4.0%** |

---

## 4. Execution & CLI Usage

### Run Unit & Regression Tests
Executes the full test suite verifying H1, H2, H4, and H5 invariants:
```bash
python code/test_regression.py
```

### Run Benchmark on Sample Requests
Evaluates the engine on the 25 public sample requests and writes `benchmark_report.md` and `failure_cases.csv`:
```bash
python code/benchmark.py
```

### Run Full 250-Request Evaluation
Runs the complete dataset and generates the validated root-level `output.csv`:
```bash
python code/main.py --mode full
```

### Backward Compatibility Flags
The system maintains full CLI switchability between V2 defaults and legacy V1 modes:
```bash
# Default V2 configuration (daily burn + reliable income filtering)
python code/main.py --mode full --burn-mode daily_burn --income-mode reliable_only

# Legacy V1 configuration (stepped variable expenses + all salary projected)
python code/main.py --mode full --burn-mode v1_stepped --income-mode v1_all
```

---

## 5. Output Verification & Data Schema

The generated `output.csv` conforms strictly to the challenge schema:
```text
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

- **Row Count**: Exactly 250 evaluation requests (`request_26` through `request_275`).
- **Solvency Invariant**: `0 <= amount_safe_to_pay <= requested_amount`.
- **Integrity**: Verified with 0 validation errors, 0 malformed dates, and 0 illegal spending changes.

---

## 6. Known Limitations

1. **Unweighted Currency Scale in MAE**: MAE is unnormalized across currencies (INR, ZAR, IDR, USD, EUR). A 1.5% balance variance in Indonesian Rupiah accounts (~1,500,000 IDR / ~$95 USD) dominates raw aggregate MAE.
2. **Conservative Solvency Buffer**: The engine strictly forbids any breach of `minimum_balance_to_keep` throughout the entire 90-day horizon. In boundary cases (e.g., `request_12`, `request_17`), this conservative stance prefers waiting for a second income cycle rather than recommending an aggressive payment plan.
