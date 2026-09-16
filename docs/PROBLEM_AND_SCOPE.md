# Problem and Scope Definition: Buy or Wait?

**Document Version**: 1.0.0  
**Phase**: Phase 1 — Production Architecture & Discovery  
**Target Product**: Consumer Financial Decision Support System ("Buy or Wait?")

---

## 1. Product Vision & Problem Statement

### 1.1 The Consumer Problem
Every day, consumers face purchase decisions where affordability is ambiguous:
- *"I have $3,000 in my checking account and want to buy a $1,200 laptop. Can I afford it today?"*
- *"A merchant offers 0% interest for 3 months on a $900 purchase. Should I pay upfront, take installments, or wait until next month's salary?"*
- *"If I buy this item now, will I breach my emergency buffer after rent, groceries, and debt payments settle next week?"*

Traditional banking apps show backward-looking transaction history and static current balances. They fail to project future solvency across complex, non-stationary cash flows (variable burn on groceries/utilities, irregular salary dates, and scheduled debits). Consumers either guess incorrectly (leading to overdrafts, missed commitments, or credit card debt) or experience excessive anxiety and delay necessary purchases.

### 1.2 The Solution: Buy or Wait?
**Buy or Wait?** is an objective, automated financial decision-support engine. When a user proposes a purchase, the system evaluates their complete forward-looking balance sheet over a 90-day cash-flow horizon and provides an evidence-based recommendation:
1. **Safe Amount Right Now**: Maximal expenditure safe today without risking downstream insolvency.
2. **Decision Verdict**:
   - `BUY` (affordable now in full).
   - `SAFER_PAYMENT` (affordable via structured payment plan, installment option, or minor discretionary spending cut).
   - `WAIT` (not affordable today, but solvent on a projected future date).
   - `NOT_RECOMMENDED` (unaffordable throughout the forecast horizon without risking financial distress).
3. **Earliest Safe Date**: Conservative calendar date when the purchase can be paid in full.
4. **Risk Tier & Stress Analysis**: Calibrated solvency risk under 90th-percentile variable expense stress (`LOW_RISK`, `MODERATE_RISK`, `HIGH_RISK`).
5. **Transparent, Grounded Explanation**: Mathematical, auditable breakdown showing starting balance, projected debits, income events, and minimum balance buffer.

---

## 2. Target Users & Core Personas

| Persona | Financial Profile | Primary Need | Typical Use Case |
|---|---|---|---|
| **Salaried Professional** | Steady monthly/bi-weekly payroll, high fixed recurring expenses (rent, loans, subscriptions). | Cash-flow timing & installment validation. | Validating major appliances ($800–$2,000), travel bookings, or gadget upgrades against salary cycles. |
| **Variable / Gig Earner** | Volatile income payouts, fluctuating grocery/transport expenses, sensitive minimum balance buffer. | Downside protection & conservative solvency. | Ensuring irregular income will cover mandatory bills before committing to discretionary purchases. |
| **Budget-Conscious Saver** | Strict savings goals, hard minimum balance to keep ($1,000+), debt aversion. | Trade-off analysis & spending modification advice. | Determining if cutting a flexible subscription allows a safe immediate purchase. |

---

## 3. Product Scope & MVP Boundaries

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             IN SCOPE (MVP)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. User Profile & Onboarding:                                               │
│    - Home currency setting (USD, EUR, GBP, INR, ZAR, IDR)                   │
│    - Current available balance & minimum balance to keep                    │
│    - Expense category preferences (protected vs stoppable vs reducible)     │
│    - Payment method preferences (cash, installment limits)                  │
│                                                                             │
│ 2. Financial Data Ingestion:                                                │
│    - Manual recurring transaction entry (salary, rent, utilities)          │
│    - CSV / OFX bank statement upload and normalization                      │
│    - Categorization & recurring cadence detection (weekly, monthly, etc.)   │
│    - User verification & correction interface for imported data             │
│                                                                             │
│ 3. Purchase Request Evaluation:                                             │
│    - Single purchase query (amount, date, merchant, category)               │
│    - Multi-option financing comparison (upfront vs 2–4 installment plans)   │
│    - Dual-track solvency evaluation (P50 expected vs P90 stressed)          │
│    - Discretionary spending change recommendations (up to 3 legal actions)  │
│                                                                             │
│ 4. Explanation & Decision Output:                                           │
│    - Structured decision payload (verdict, safe amount, plan, dates, risk)  │
│    - Deterministic ledger audit trail (day-by-day closing balances)         │
│    - Natural language summary generated with strict factual grounding       │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          OUT OF SCOPE (Deferred)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Open Banking / Live Aggregators (Plaid, Yodlee, Setu, Salt Edge)         │
│    - Deferred to Phase 2 to eliminate third-party compliance overhead.      │
│                                                                             │
│ 2. Payment Execution & Fund Movement:                                       │
│    - The system never moves money, initiates ACH/wire transfers, or debits  │
│      user bank accounts. It is strictly decision-support advisory.          │
│                                                                             │
│ 3. Credit Scoring & Underwriting:                                           │
│    - Not an external credit score or lending approval tool.                 │
│                                                                             │
│ 4. Investment & Tax Advice:                                                 │
│    - Non-cash asset valuation, capital gains tax, and equity trading are    │
│      explicitly excluded. Non-cash assets do not count as liquid cash.      │
│                                                                             │
│ 5. Automated Merchant Scraping / Browser Extensions:                        │
│    - Manual purchase input or webhooks only in MVP.                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. System Inputs & Outputs

### 4.1 System Inputs
1. **Financial Profile**:
   - `user_id`: UUID
   - `home_currency`: ISO-4217 (USD, EUR, INR, etc.)
   - `current_available_balance`: Verified liquid checking/savings balance.
   - `minimum_balance_to_keep`: Mandatory emergency/safety buffer.
   - `protected_categories`: Expense types never to be cut (e.g., rent, healthcare).
   - `reducible_categories`: Categories user is willing to reduce (e.g., groceries, dining).
   - `stoppable_categories`: Categories user is willing to pause (e.g., gym, streaming).
   - `max_installment_months`: Integer or null (if installments rejected).
2. **Transaction History & Schedules**:
   - Settled transactions (past 90–180 days) for burn rate and cadence inference.
   - Explicit scheduled debits (upcoming bills, loans).
   - Confirmed scheduled income (verified payroll).
3. **Purchase Request**:
   - `requested_amount`: Positive decimal.
   - `currency`: ISO-4217.
   - `request_date`: Calendar date.
   - `desired_completion_date`: Deadline date.
   - `allows_partial_payment`: Boolean.
   - `available_payment_options`: List of financing options (down payment, terms, interest).

### 4.2 System Outputs
1. **`verdict`**: `BUY` | `SAFER_PAYMENT` | `WAIT` | `NOT_RECOMMENDED`.
2. **`amount_safe_to_pay`**: Exact currency amount safe to expend immediately.
3. **`recommended_payment_method`**: `full_payment` | `partial_payment` | `installments` | `wait` | `not_recommended`.
4. **`payment_plan`**: Chronological schedule of safe payment dates and amounts (`YYYY-MM-DD:amount|...`).
5. **`earliest_safe_date`**: Calendar date when 100% full payment is safe, or null.
6. **`risk_tier`**: `LOW_RISK` | `MODERATE_RISK` | `HIGH_RISK`.
7. **`spending_changes_needed`**: Zero to 3 concrete actions (`stop:<event_id>` or `reduce_to:<event_id>:<amount>`).
8. **`audit_ledger`**: 90-day daily closing balance projections under expected and stressed conditions.
9. **`explanation`**: Concise, human-readable breakdown grounded strictly in ledger facts.

---

## 5. Explicit Constraints & Operating Assumptions

### 5.1 Facts
- The V2/V3 engine is deterministic, written in Python, uses `Decimal` arithmetic, and has zero floating-point drift.
- V3 includes validated category-specific P90 stress multipliers derived from empirical out-of-time test residuals (Groceries: +24.0%, Transport: +24.2%, Dining: +23.9%, Utilities: +12.5%, etc.).
- The engine operates offline without requiring external LLM or cloud model calls for financial calculation.
- The engine runs a 90-day simulation in <50ms per request on modern hardware.

### 5.2 Assumptions
- **Moderate Deployment Scale**: Initial target is 5,000 to 50,000 active users; peak traffic 20–50 requests/second.
- **Interactive Latency**: Users expect purchase evaluation responses in <1.5 seconds.
- **Single Modular Monolith**: A unified backend service with PostgreSQL and Redis meets all latency and throughput requirements with minimal operational complexity.
- **LLM Safety Boundary**: If an LLM is used to rephrase explanations or extract transaction entities, it must never compute numbers, alter plans, or override solvency constraints.

### 5.3 Unknowns & Unresolved Questions
1. **Bank Statement Schema Heterogeneity**: Real-world bank CSV exports lack a single standard (varying date formats, split debit/credit columns, sign conventions). A robust parsing and user-mapping step is required.
2. **Multi-Currency Real-World Accounts**: Does the user hold multiple bank accounts in different currencies, or a single account with foreign transaction conversion? (MVP assumes single home currency with spot conversion).
3. **Regulatory Classification**: Depending on the deployment jurisdiction (e.g., CFPB in US, FCA in UK, SEBI/RBI in India), automated advice tools require explicit disclaimers: *"Decision-support only; not licensed financial advice or credit underwriting."*

---

## 6. Success Metrics & Key Performance Indicators (KPIs)

| Metric | Target | Measurement Method |
|---|---|---|
| **Solvency Preservation Rate** | **100.0%** under baseline; **>95.0%** under P90 stress | 0 simulated balance breaches below `minimum_balance_to_keep`. |
| **Evaluation Latency** | **< 250ms** engine / **< 1.0s** end-to-end API | P95 latency measured from HTTP request to response. |
| **Ingestion Completion Rate** | **> 85.0%** | % of users who successfully import statements and approve transactions. |
| **Unsafe Approval Rate** | **0.0%** | Zero recommendations of `full_payment` when P50 safe amount < requested amount. |
| **False Conservatism Rate** | **< 5.0%** | Requests unnecessarily downgraded to `wait` when P90 headroom is ample. |
| **System Uptime** | **99.9%** | Production API availability. |
