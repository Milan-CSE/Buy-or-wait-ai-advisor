# Grounded Explanation Engine Specification

**Buy or Wait? Financial Decision Support Platform**  
**Milestone 7: Observability + Grounded Explanation**

---

## 1. Grounding Philosophy & Invariants

Financial decision-support systems must provide clear, human-understandable guidance without hallucinations, unsupported promises, or false precision. The `ExplanationService` implements a strictly deterministic narrative layer directly grounded in the evaluated `DecisionResult` artifact.

### The 9 Grounding Invariants

1. **Zero Invented Amounts**: Every currency figure appearing in the explanation text (e.g. safe amount, requested amount, headroom, minimum balance) must be identical to the values in `DecisionResult` or `PurchaseProposal`.
2. **Zero Invented Dates**: Any future safe payment date mentioned in the explanation must match `earliest_date_for_full_payment` exactly.
3. **No Guarantee or Absolute Promise Language**: Phrasing such as *"guaranteed"*, *"guarantee"*, *"foolproof"*, *"100% safe"*, or *"promise"* is strictly prohibited. Financial solvency is probabilistic and subject to external volatility.
4. **Exact Verdict Alignment**:
   - `BUY`: Affirms upfront solvency while reinforcing minimum balance preservation.
   - `SAFER_PAYMENT`: Explains why upfront payment is unsafe and outlines the recommended installment or partial plan.
   - `WAIT`: Specifies the exact earliest date when projected cashflow restores solvency.
   - `NOT_RECOMMENDED`: Explains that the purchase exceeds capacity throughout the entire 90-day horizon.
5. **Separation of Base vs. Stress Risk**: Explanations explicitly present both expected conditions (P50) and stress conditions (P90) so users understand what occurs during unexpected expenditure spikes.
6. **Actionable Recommendations**: Every response supplies a clear, concise `suggested_action` advising the user on concrete next steps.
7. **Safe Handling of Data Insufficiency**: When financial evidence is incomplete (`DATA_INSUFFICIENT`), the system halts decisioning and clearly outlines the missing data and remediation steps.
8. **Deterministic Re-evaluation**: Identical financial inputs always generate byte-for-byte identical explanation objects.
9. **Traceable Fact DTO**: All prose is paired with a structured `supporting_facts` dictionary enabling user interfaces and compliance auditors to verify every claim.

---

## 2. Explanation Schema & Response Format

The `ExplanationService` emits a structured `GroundedExplanation` containing five core fields:

```json
{
  "headline": "Purchase is safe to complete today",
  "concise_explanation": "Your requested purchase of USD 250.00 is fully within your safe spending capacity of USD 250.00. All projected cashflow commitments are satisfied while preserving your USD 500.00 minimum balance.",
  "supporting_facts": {
    "requested_amount": "250.00",
    "safe_amount": "250.00",
    "currency": "USD",
    "verdict": "BUY",
    "affordability_status": "affordable_now",
    "recommended_payment_method": "full_payment",
    "payment_plan": "none",
    "earliest_date_for_full_payment": "2026-09-15",
    "reserve_required": "500.00",
    "risk_tier": "LOW_RISK",
    "headroom_p50": "1250.00",
    "headroom_p90": "980.00",
    "safe_amount_p50": "250.00",
    "safe_amount_p90": "250.00",
    "stress_summary": "Reserves remain intact under P90 stress",
    "spending_changes_needed": "none"
  },
  "risk_explanation": "Low risk profile: Even under 90th-percentile simulated expenditure stress, your projected cash balance maintains a safety headroom of USD 980.00.",
  "suggested_action": "Proceed with upfront full payment."
}
```

---

## 3. Verdict-Specific Explanation Strategies

### A. BUY (`affordable_now`)
- **Headline**: *"Purchase is safe to complete today"*
- **Prose**: Demonstrates that the purchase fits within `amount_safe_to_pay` and maintains the user's `minimum_balance_to_keep`.
- **Suggested Action**: *"Proceed with upfront full payment."*

### B. SAFER_PAYMENT (`affordable_with_plan`)
- **Headline**: *"Purchase is affordable using a recommended payment plan"*
- **Prose**: Clarifies that full upfront payment would compromise liquid reserves, but an available installment or partial-payment schedule is solvent.
- **Suggested Action**: *"Select the recommended payment plan (<payment_plan>) rather than paying upfront."*

### C. WAIT (`affordable_later`)
- **Headline**: *"Wait until upcoming cashflow improves your balance"*
- **Prose**: Identifies that funds are insufficient today, but scheduled future income (e.g. salary settlement) makes the purchase safe on or after `earliest_date_for_full_payment`.
- **Suggested Action**: *"Delay the purchase until <earliest_date_for_full_payment> when funds become safe."*

### D. NOT_RECOMMENDED (`not_affordable`)
- **Headline**: *"Purchase not recommended within forecast horizon"*
- **Prose**: Explains that the purchase exceeds safe capacity across the forecast window without acceptable options.
- **Suggested Action**: *"Do not proceed with this purchase at this time, or consider a significantly smaller purchase amount."*

### E. DATA_INSUFFICIENT (Quality Gate Pause)
- **Headline**: *"Evaluation cannot proceed due to insufficient financial data"*
- **Prose**: Cites the missing required evidence (e.g., stale balance, missing checking account, unverified transactions).
- **Suggested Action**: Emits the exact user remediation string (e.g. *"Link or upload statements for an active checking account"*).

---

## 4. Risk Communication Architecture

Risk tiers are derived empirically from P90 residual uncertainty buffers:

- **LOW_RISK**: Stressed expenditure simulations maintain positive headroom above `minimum_balance_to_keep`.
- **MODERATE_RISK**: Solvency is intact under normal conditions (P50), but stressed expenses narrow headroom.
- **HIGH_RISK**: Stressed expenditure simulations breach minimum reserve thresholds.
