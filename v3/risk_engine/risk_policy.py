"""
v3/risk_engine/risk_policy.py

Defines Controlled Integration Policies for applying P90 risk awareness:

Policy 1: CONSERVATIVE_SOLVENCY (Strict)
  - If risk tier is MODERATE_RISK or HIGH_RISK, never recommend full immediate payment.
  - Require the recommendation to be safe under P90 stress.

Policy 2: RISK_ADAPTIVE (Balanced - Recommended)
  - If LOW_RISK: recommend V2 optimal plan.
  - If MODERATE_RISK:
      - If an installment plan exists that is solvent under P90 stress, recommend installments.
      - If no installment plan is safe under P90 stress, recommend wait until next confirmed income.
      - Append risk disclaimer to decision explanation.
  - If HIGH_RISK: keep V2 wait / not_recommended.

Policy 3: SHADOW_AUDIT_ONLY (Zero Behavior Change)
  - V2 decision is unchanged; risk profile is logged in diagnostics.
"""
from __future__ import annotations
import copy
from decimal import Decimal
from typing import Dict, Optional

import sys, os
sys.path.insert(0, os.path.abspath('code'))
from ranker import Decision

from v3.risk_engine.risk_classifier import RiskProfile


def apply_risk_policy(
    v2_decision: Decision,
    v3_p90_decision: Decision,
    risk: RiskProfile,
    policy: str = 'shadow_audit_only',
) -> Decision:
    """
    Applies the selected risk policy to produce the integrated decision.
    Default policy is 'shadow_audit_only', which strictly preserves V2 decisions.
    """
    if policy == 'shadow_audit_only':
        return copy.deepcopy(v2_decision)

    if risk.risk_tier == 'LOW_RISK':
        dec = copy.deepcopy(v2_decision)
        dec.decision_explanation = f"{dec.decision_explanation} [Solvency Risk: LOW - robust under P90 stress]"
        return dec

    if risk.risk_tier == 'MODERATE_RISK':
        if policy == 'risk_adaptive':
            # Check if P90 allows an installment plan
            if v3_p90_decision.recommended_payment_method == 'installments':
                dec = copy.deepcopy(v3_p90_decision)
                dec.decision_explanation = (
                    f"{dec.decision_explanation} [Risk-Aware Adjustment: installments selected "
                    f"to prevent minimum balance breach under 90th-percentile spending stress]"
                )
                return dec
            elif v2_decision.recommended_payment_method in ('full_payment', 'partial_payment'):
                # Downgrade full payment to wait to prevent risk of minimum balance breach
                dec = copy.deepcopy(v3_p90_decision)
                dec.decision_explanation = (
                    f"Waiting recommended: safe on expected spend, but vulnerable to typical 90th-percentile "
                    f"variable spending spikes ({risk.p90_headroom:.2f} headroom vs {risk.requested_amount:.2f} requested)."
                )
                return dec
            else:
                return copy.deepcopy(v2_decision)
        elif policy == 'conservative_solvency':
            return copy.deepcopy(v3_p90_decision)

    # HIGH_RISK
    return copy.deepcopy(v2_decision)
