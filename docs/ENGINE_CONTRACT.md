# Buy or Wait? Financial Decision Engine Contract

**Package**: `buyorwait_engine`  
**Version**: `1.0.0`  
**Calibration Version**: `v3_empirical_q90_20260914`  
**Status**: Production Domain Library (Extracted & Hardened)

---

## 1. Overview & Architectural Boundaries

`buyorwait_engine` is a pure Python domain library providing deterministic cash-flow forecasting, multi-option purchase affordability evaluations, and empirical P90 expenditure stress testing.

### Decoupling Guarantees
1. **Zero Filesystem Coupling**: The engine never reads from `dataset/`, disk files, or environment variables directly. All state, profiles, transactions, FX rates, and purchase options are passed in memory as typed domain objects.
2. **Deterministic Arithmetic**: All monetary quantities require Python `Decimal`. Floating-point numbers are strictly rejected with `TypeError` to eliminate rounding drift.
3. **State Immutability**: The baseline `FinancialState` is never mutated during candidate evaluation or stress testing; stress testing operates on an isolated deepcopy.
4. **Backward Compatibility**: Legacy adapters (`buyorwait_engine.adapters.legacy`) provide 100% exact parity with the frozen V2 deterministic engine and V3 risk engine.

---

## 2. Public API Interface

```python
import buyorwait_engine as bow

# 1. Initialize configured engine facade
engine = bow.BuyOrWaitEngine(
    risk_config=bow.RiskCalibrationConfig(),
    risk_policy="shadow_audit_only",  # 'shadow_audit_only' | 'risk_adaptive' | 'conservative_solvency'
    fx=bow.FXEngine(),
)

# 2. Evaluate purchase proposal directly from domain inputs
decision: bow.DecisionResult = engine.evaluate(
    profile=profile_input,
    events=cashflow_events,
    purchase=purchase_proposal,
)
```

Alternatively, evaluate directly against a pre-built `FinancialState`:

```python
state = bow.build_financial_state_from_inputs(profile_input, cashflow_events, as_of_date=purchase.request_date)
decision: bow.DecisionResult = bow.evaluate_purchase(state, purchase_proposal)
```

---

## 3. Domain Model Specifications

### 3.1 Input DTOs

#### `PurchaseProposal`
| Field | Type | Description | Constraints |
|---|---|---|---|
| `request_id` | `str` | Unique proposal identifier | Required |
| `user_id` | `str` | Tenant user identifier | Required |
| `requested_amount` | `Decimal` | Proposed purchase cost | Must be `Decimal > 0` |
| `currency` | `str` | ISO currency code (e.g., `'USD'`) | Required |
| `request_date` | `datetime.date` | Date of the proposal | Required |
| `desired_completion_date`| `datetime.date` | Purchase deadline | Must be `\ge request_date` |
| `allows_partial_payment` | `bool` | Whether partial settlement is permitted | Default: `True` |
| `payment_options` | `List[PaymentOptionInput]`| Financing options from seller/lender | Default: `[]` |

#### `FinancialProfileInput`
| Field | Type | Description |
|---|---|---|
| `user_id` | `str` | Unique user identifier |
| `home_currency` | `str` | Base accounting currency |
| `current_available_balance` | `Decimal` | Liquid cash balance |
| `minimum_balance_to_keep` | `Decimal` | Emergency reserve buffer ($\ge 0$) |
| `protected_categories` | `Sequence[str]` | Non-negotiable expense categories |
| `reducible_categories` | `Sequence[str]` | Discretionary categories that can be reduced |
| `stoppable_categories` | `Sequence[str]` | Subscriptions/services that can be paused |
| `payment_methods` | `Sequence[str]` | User-accepted payment rails |
| `max_installment_months` | `Optional[Decimal]` | Maximum acceptable installment term |

#### `CashflowEventInput`
| Field | Type | Description |
|---|---|---|
| `event_id` | `str` | Unique transaction ID |
| `event_type` | `str` | Event classification (`'salary'`, `'expense'`, etc.) |
| `category` | `str` | Spending or income category |
| `direction` | `str` | `'debit'`, `'credit'`, or `'non_cash'` |
| `amount` | `Decimal` | Event amount in `currency` |
| `currency` | `str` | Transaction currency |
| `status` | `str` | `'settled'`, `'pending'`, `'scheduled'`, `'cancelled'`, `'failed'` |
| `settlement_date` | `Optional[date]` | Actual or scheduled settlement date |

---

### 3.2 Output DTO: `DecisionResult`

```python
@dataclass(frozen=True)
class DecisionResult:
    request_id: str
    verdict: str                        # 'BUY' | 'SAFER_PAYMENT' | 'WAIT' | 'NOT_RECOMMENDED'
    amount_safe_to_pay: Decimal         # Immediate safe payment amount on request_date
    affordability_status: str           # 'affordable_now' | 'affordable_with_plan' | 'affordable_later' | 'not_affordable'
    recommended_payment_method: str     # 'full_payment' | 'partial_payment' | 'installments' | 'wait' | 'not_recommended'
    payment_plan: str                   # 'none' or 'YYYY-MM-DD:amt|...'
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str        # 'none' or 'stop:X|reduce_to:Y:Z'
    decision_explanation: str           # Evidence-grounded rationale
    risk_assessment: Optional[RiskAssessmentResult] = None
    audit_metrics: Dict[str, Any] = field(default_factory=dict)
```

---

## 4. Risk Engine Provenance & Uncertainty Modeling

### 4.1 Calibration Provenance
- **Calibration Version**: `v3_empirical_q90_20260914`
- **Methodology**: Calibrated out-of-time on empirical residual distribution quantiles ($Q_{0.90}$) across 250 evaluation users.
- **Multipliers**:
  - `groceries`: $+24.0\%$ (`1.240`)
  - `transport`: $+24.2\%$ (`1.242`)
  - `dining`: $+23.9\%$ (`1.239`)
  - `utilities`: $+12.5\%$ (`1.125`)
  - `shopping`: $+12.6\%$ (`1.126`)
  - `entertainment`: $+12.2\%$ (`1.122`)
  - `healthcare`: $+10.7\%$ (`1.107`)
  - `personal_care`: $+15.0\%$ (`1.150`)
  - Fixed commitments (`rent`, `debt_repayment`, subscriptions): $+0.0\%$ (`1.000`)

> [!IMPORTANT]
> **Heuristic Disclaimer**: These multipliers represent empirical stress buffers derived from historical expenditure volatility in the evaluation cohort. They do not constitute mathematical insolvency guarantees or theoretical statistical coverage bounds.

### 4.2 Risk Tiers
- **`LOW_RISK`**: `p90_safe_amount \ge requested_amount`. The user maintains positive headroom above `minimum_balance_to_keep` throughout the entire 90-day forecast even under 90th-percentile expenditure shocks.
- **`MODERATE_RISK`**: `p50_safe_amount \ge requested_amount > p90_safe_amount`. Affordable under normal cash flow, but vulnerable to typical expenditure spikes.
- **`HIGH_RISK`**: `p50_safe_amount < requested_amount`. Immediate purchase breaches minimum balance under baseline expected cash flow.

---

## 5. Verification & Test Suite

The library is verified by an automated test suite in `buyorwait_engine/tests/`:
1. `test_domain_models.py`: Strict Decimal type checking, date ordering, positive amounts, profile immutability.
2. `test_fx.py`: Direct conversions, multi-currency USD triangulation, missing rate error handling.
3. `test_engine_contract.py`: Pure in-memory invocation, balance shortfall fallback, max installment duration filtering, state immutability.
4. `test_parity_v2.py`: Exact 25/25 parity comparison against the frozen V2 decision pipeline.
