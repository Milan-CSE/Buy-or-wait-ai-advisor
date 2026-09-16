"""
buyorwait_engine/risk/policy.py

Controlled integration policies for applying P90 risk awareness:
- shadow_audit_only (Default: zero behavior change)
- risk_adaptive (Balanced)
- conservative_solvency (Strict)
"""
from __future__ import annotations
import copy
from typing import Optional

from buyorwait_engine.decision.ranker import Decision
from buyorwait_engine.risk.classifier import RiskProfile


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
            if v3_p90_decision.recommended_payment_method == 'installments':
                dec = copy.deepcopy(v3_p90_decision)
                dec.decision_explanation = (
                    f"{dec.decision_explanation} [Risk-Aware Adjustment: installments selected "
                    f"to prevent minimum balance breach under 90th-percentile spending stress]"
                )
                return dec
            elif v2_decision.recommended_payment_method in ('full_payment', 'partial_payment'):
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

    return copy.deepcopy(v2_decision)
