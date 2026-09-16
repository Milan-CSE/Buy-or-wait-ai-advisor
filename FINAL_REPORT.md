# Final Project Report: Buy or Wait? AI Financial Decision & Risk Intelligence System

**Challenge / Project**: HackerRank Orchestrate — *Buy or Wait?*  
**Architecture Version**: V2 (Deterministic Solvency Core) + V3 (Statistical & ML Risk Engine)  
**Status**: Production Complete & Frozen  
**Runtime**: Python 3.14 / Zero Cloud Dependencies / Zero Floating-Point Drift (`Decimal`)

---

## 1. Executive Summary & Problem Formulation

In modern consumer finance, automated payment decisioning systems must balance two conflicting objectives:
1. **Financial Solvency**: Guaranteeing that a user never breaches their required minimum balance over a multi-month horizon after accounting for fixed debt, recurring commitments, and volatile essential spending.
2. **Affordability Maximization**: Recommending actionable, least-cost payment plans (full immediate payment, seller installments, or structured partial payments) that satisfy user preferences and completion deadlines.

*Buy or Wait?* challenges an AI agent to evaluate real-world purchase requests across hundreds of users in 5 fiat currencies (INR, ZAR, IDR, USD, EUR). The system must ingest non-stationary financial event streams, dated foreign exchange rates, seller financing options, and unstructured message amendments, ultimately deciding whether the user should pay now, pay via installments, wait, or decline.

### Engineering Philosophy: Deterministic Solvency vs Statistical Forecasting
A core design principle of this project is **separation of concerns**:
- **Solvency Authority**: A pure deterministic accounting ledger (`forecast.py`, `safe_amount.py`, `ranker.py`) evaluates exact daily balances using arbitrary-precision `Decimal` arithmetic. Machine learning is **never permitted to override solvency constraints**.
- **Forecasting & Risk Quantification**: Statistical time-series estimators and empirical quantile uncertainty buffers (`v3/forecasting/`, `v3/uncertainty/`, `v3/risk_engine/`) model expected expense trends and tail-risk volatility.

---

## 2. Final System Architecture

```
                                [Dataset Ingestion]
                   (profiles, events, exchange_rates, requests, messages)
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │    Lifecycle & Currency Engine        │
                     │  - Holds pending debits in reserve    │
                     │  - Suppresses unconfirmed credits     │
                     │  - Exact settlement-dated FX lookups  │
                     └───────────────────────────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │      Financial State Constructor      │
                     │  - H1: Daily burn variable smoothing  │
                     │  - H2: Income reliability classifier  │
                     └───────────────────────────────────────┘
                                         │
                          P50 Baseline FinancialState
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
    ┌───────────────────────────┐                 ┌───────────────────────────┐
    │    V2 Decision Track      │                 │    V3 Risk Engine Track   │
    │  - 90-day daily ledger    │                 │  - Validated P90 buffers  │
    │  - Binary search safe amt │                 │  - Deep-copied state      │
    │  - H4: Spending optimizer │                 │  - Stressed daily ledger  │
    │  - H5: Earliest date scan │                 │  - Headroom & breach eval │
    │  - Lexicographical ranker │                 │  - Risk tier assignment   │
    └───────────────────────────┘                 └───────────────────────────┘
                 │                                               │
            V2 Decision                                     V3 P90 Decision
                 │                                          & RiskProfile
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │       Controlled Risk Policy          │
                     │  - shadow_audit_only (Default)        │
                     │  - risk_adaptive (Balanced)           │
                     │  - conservative_solvency (Strict)     │
                     └───────────────────────────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
          [output.csv]                                    [output_v3.csv]
   (8 Columns, 100% V2 Compliant)                 (17 Columns, Full Risk Audit)
```

---

## 3. Key Hypotheses & Experimental Progression

### V2 Deterministic Progression (H1 through H5)

| Hypothesis | Target | Investigation & Implementation | Outcome | Status |
|---|---|---|---|:---:|
| **H1: Variable Expense Timing** | `amount_safe_to_pay` | V1 discrete variable expense clustering created artificial cashflow dips. Converted variable expenses to empirical daily burn rates based on observed cadence. | Slashed benchmark MAE from 190,594.67 to 116,646.04 (-38.8%) with zero categorical regressions. | **ACCEPTED** |
| **H2: Income Reliability Classification** | Safe amount on gig income | Variable platform payouts (*"Delivery platform payout"*) were erroneously projected as recurring guaranteed salary. Introduced `is_salary_reliable_for_forecast()`. | Reduced `request_10` error by 95% (from 254,000 to 12,700 INR). Reduced benchmark MAE to 106,994.04 (-43.9% vs V1). | **ACCEPTED** |
| **H3: Expense Forecasting Cadence & Amount Adjustments** | Residual expense errors | Tested 6 alternative estimators (rolling means, medians, lookback windows). Analysis revealed 99% of raw MAE was driven by IDR currency scale (~15,500 IDR/USD, representing ~1.5% balance variance). | All 6 alternatives degraded MAE (+11% to +80%) or caused regressions. Rejected to protect generalization. | **REJECTED** |
| **H4: Spending Change Optimization** | `spending_changes_needed` | Resolved 5 mismatches where `reduce_to` picked daily-burn scaled amounts instead of catalog minimums, and `wait`/`not_recommended` prescribed cuts. Mapped reductions to original `minimum_allowed_amount`. | Improved spending change accuracy from 20/25 (80.0%) to 23/25 (92.0%). | **ACCEPTED** |
| **H5: Earliest Date Preservation** | `earliest_date_for_full_payment` | Ranker previously cleared `earliest_date_for_full_payment` when a request missed user deadline. Decoupled objective solvency date scan from subjective deadline filtering. | Corrected `request_06` (`2026-01-15`), raising earliest date accuracy to 22/25 (88.0%). | **ACCEPTED** |

---

### V3 AI/ML Risk Progression (Phases 1 through 3)

#### Phase 1: Forecasting Foundation (Temporal Splitting & Point Forecasting)
- **Methodology**: Built reproducible temporal splitting on 2,444 individual series with zero lookahead (15,438 train / 8,018 test observations). Evaluated 6 statistical baselines against a gradient boosted decision tree (`HistGradientBoostingRegressor`) using 21 scale-invariant features.
- **Results**:
  - `rolling_mean_8`: **Best overall point forecast** on variable categories (MASE 0.9599, sMAPE 14.08%).
  - `HistGBM (ML)`: MASE 1.0167 on variable categories. Feature importance showed the model converged to approximating `rolling_median_8` (relative importance +0.143) but introduced 69.3% underestimation rate.
- **Decision**: **HistGBM was REJECTED**. `rolling_mean_8` was accepted as the expected P50 spend baseline.

#### Phase 2: Uncertainty Quantification (Residual Modeling)
- **Methodology**: Evaluated out-of-time residual errors ($r = y - \hat{y}$) across 4 statistical estimators and a multi-quantile ML model (`HistGradientBoostingRegressor(loss='quantile')` for $q \in \{0.50, 0.75, 0.90\}$).
- **Results**:
  - `category_empirical`: Achieved textbook out-of-time calibration on variable expenses:
    - P50 Coverage: **49.7%** (Target: 50.0%)
    - P75 Coverage: **74.9%** (Target: 75.0%)
    - P90 Coverage: **90.1%** (Target: 90.0%)
    - Cumulative 90-day horizon coverage: **97.4%**
  - `QuantileGBM (ML)`: P90 coverage only reached **83.5%** (under-predicting tail risk by 6.5 percentage points).
- **Decision**: **QuantileGBM was REJECTED**. `category_empirical` was accepted as the validated P90 uncertainty model.

#### Phase 3: Risk-Aware Solvency Integration
- Derived calibrated P90 multipliers for variable categories:
  - Groceries: `+24.0%`
  - Transport: `+24.2%`
  - Dining: `+23.9%`
  - Utilities: `+12.5%`
  - Shopping: `+12.6%`
  - Entertainment: `+12.2%`
  - Healthcare: `+10.7%`
  - Fixed Categories (Rent, Debt, Subscriptions): `+0.0%`
- Built dual-track solvency simulation comparing P50 expected headroom against P90 stressed headroom.

---

## 4. Accepted vs. Rejected Decisions Summary

```
┌────────────────────────────────────────────────────────────────────────────┐
│                       DECISION MATRIX SUMMARY                              │
├──────────────────────────────────────┬─────────────┬───────────────────────┤
│ Component / Proposal                 │ Decision    │ Primary Rationale     │
├──────────────────────────────────────┼─────────────┼───────────────────────┤
│ Daily Burn Variable Smoothing (H1)   │ ACCEPTED    │ -38.8% MAE reduction  │
│ Income Reliability Classifier (H2)   │ ACCEPTED    │ Suppressed gig hazard │
│ Heuristic Expense Retuning (H3)      │ REJECTED    │ Degraded MAE (+11-80%)│
│ Spending Change Catalog Mapping (H4) │ ACCEPTED    │ 92.0% accuracy        │
│ Earliest Date Decoupling (H5)        │ ACCEPTED    │ 88.0% accuracy        │
│ HistGBM Point Regressor (V3 Phase 1) │ REJECTED    │ 69.3% underestimation │
│ Rolling Mean 8 Baseline (V3 Phase 1) │ ACCEPTED    │ MASE 0.9599           │
│ QuantileGBM Uncertainty (V3 Phase 2) │ REJECTED    │ Failed tail coverage  │
│ Category Empirical P90 (V3 Phase 2)  │ ACCEPTED    │ 90.1% exact P90 cov   │
│ Shadow Audit Integration (V3 Phase 3)│ ACCEPTED    │ Zero V2 regression    │
└──────────────────────────────────────┴─────────────┴───────────────────────┘
```

---

## 5. Benchmark Performance & Validation Metrics

### Deterministic Accuracy (25 Public Sample Requests)

| Metric | V1 Baseline | V2 Final | Improvement |
|---|:---:|:---:|:---:|
| **`recommended_payment_method`** | 22 / 25 (88.0%) | **24 / 25 (96.0%)** | **+8.0%** |
| **`affordability_status`** | 22 / 25 (88.0%) | **23 / 25 (92.0%)** | **+4.0%** |
| **`payment_plan`** | 22 / 25 (88.0%) | **23 / 25 (92.0%)** | **+4.0%** |
| **`spending_changes_needed`** | 19 / 25 (76.0%) | **23 / 25 (92.0%)** | **+16.0%** |
| **`earliest_date_for_full_payment`** | 21 / 25 (84.0%) | **22 / 25 (88.0%)** | **+4.0%** |
| **`amount_safe_to_pay` MAE** | 190,594.67 | **106,994.04** | **-43.9%** |
| **Exact 7-Field Matches** | 2 / 25 (8.0%) | **3 / 25 (12.0%)** | **+4.0%** |

### V3 Full Dataset Evaluation Profile (250 Requests)
- **Total Requests Processed**: 250
- **Execution Time**: 200.4s (~0.80s/req for full dual-track simulation)
- **Risk Tier Distribution**:
  - `LOW_RISK`: 56 requests (22.4%) — Solvency preserved under P90 stress.
  - `MODERATE_RISK`: 17 requests (6.8%) — Baseline safe, but vulnerable to spending spikes.
  - `HIGH_RISK`: 177 requests (70.8%) — Baseline safe capacity insufficient.
- **P90 Divergence Rate**: 175 / 250 requests (70.0%) exhibit reduced headroom or require conservative restructuring under P90 stress.
- **Validation Errors**: 0 errors across all 250 rows.

### V3 Uncertainty Calibration (8,018 Out-of-Time Test Observations)

| Category Group | P50 Coverage (Target: 50%) | P75 Coverage (Target: 75%) | P90 Coverage (Target: 90%) | Underest Rate (P90) |
|---|:---:|:---:|:---:|:---:|
| **Variable Spending** | **49.7%** | **74.9%** | **90.1%** | **9.9%** |
| **Fixed Spending** | 100.0% | 100.0% | 100.0% | 0.0% |
| **Overall Dataset** | 62.4% | 81.3% | 92.6% | 7.4% |

---

## 6. Why Model Tuning Stopped

Research and model iteration were formally frozen upon completion of Phase 3 for three empirical reasons:
1. **Convergence on Real Signal**: Tree-based gradient boosting models (HistGBM and QuantileGBM) on tabular financial time series did not outperform robust statistical baselines. Financial transaction amounts exhibit high idiosyncratic noise and regime shifts; complex non-linear models tended to fit sample noise rather than extract generalizable patterns.
2. **Asymmetric Risk in Financial Solvency**: In credit and solvency decisioning, under-forecasting expenses (under-coverage) is vastly more dangerous than over-conservatism. Empirical quantile buffers derived from out-of-time residuals provided mathematically calibrated coverage (90.1%) that machine learning models failed to guarantee (83.5%).
3. **Auditability and Compliance**: The dual-track architecture guarantees complete explainability. Financial regulators and consumers require clear, interpretable justifications (e.g., *"Groceries stressed by +24.0% creates a 350.00 ZAR deficit against minimum balance"*), which pure black-box models obfuscate.

---

## 7. Known Limitations

1. **Unweighted Currency Scaling**: The unweighted MAE metric is dominated by high-denomination currencies (Indonesian Rupiah at ~15,500 IDR/USD). While normalized error metrics (MASE, sMAPE) are well-behaved, aggregate MAE reflects currency scale rather than model defect.
2. **Empirical Quantile Stationarity**: P90 stress factors assume expense volatility distributions remain stationary over the 90-day forecast. Exogenous macroeconomic shocks (hyperinflation, unexpected currency devaluations) are outside the model horizon.
3. **Binary Income Reliability**: Income is either admitted at 100% of confirmed employer payroll or excluded (0%). A continuous probabilistic income arrival model represents an area for future work.

---

## 8. Next-Stage High-Level Opportunities

*These items are documented for long-term product vision; no code changes are proposed:*

1. **Multimodal LLM Evidence Reasoning**: Utilize Vision-Language Models (VLMs) to parse unstructured receipt images (`dataset/media/images/`) and message conversations to dynamically adjust recurring debit cancellation dates.
2. **Adaptive Horizon Solvency**: Extend the fixed 90-day ledger simulation to dynamic horizons based on purchase duration (e.g., 6-month or 12-month installment products).
3. **Counterfactual Budget Planner**: Generate actionable recommendations indicating which discretionary subscriptions the user can reduce to make a currently unaffordable purchase safe within 30 days.

---

## 9. Verification & Audit Sign-Off

- **Unit & Regression Tests**: 10/10 V2 tests pass (`code/test_regression.py`), 20/20 V3 tests pass (`v3/tests/`).
- **Benchmark Consistency**: V2 benchmark matches ground truth at 96% payment method, 92% affordability, 92% plan, 92% spending changes.
- **V2 Output Byte-for-Byte Preservation**: Under default `shadow_audit_only`, V3 preserves V2 `output.csv` decisions identically.
- **Contract Schema**: Fully adheres to HackerRank challenge format and emits extended audit report (`output_v3.csv`).
