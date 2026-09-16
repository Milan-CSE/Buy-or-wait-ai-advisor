"""
buyorwait_engine/risk/classifier.py

Classifies solvency risk into LOW_RISK, MODERATE_RISK, and HIGH_RISK
by comparing baseline (P50) headroom against stress (P90) headroom.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from buyorwait_engine.domain.state import FinancialState
from buyorwait_engine.domain.models import RiskAssessmentResult
from buyorwait_engine.forecast.ledger import build_ledger
from buyorwait_engine.decision.safe_amount import compute_safe_amount
from buyorwait_engine.risk.config import CURRENT_CALIBRATION_VERSION, DEFAULT_P90_STRESS_FACTORS, RiskCalibrationConfig


@dataclass
class RiskProfile:
    request_id: str
    user_id: str
    currency: str
    requested_amount: Decimal
    minimum_balance_to_keep: Decimal
    p50_min_closing: Decimal
    p90_min_closing: Decimal
    p50_safe_amount: Decimal
    p90_safe_amount: Decimal
    p50_headroom: Decimal
    p90_headroom: Decimal
    breach_under_p50: bool
    breach_under_p90: bool
    post_payment_breach_p50: bool
    post_payment_breach_p90: bool
    risk_tier: str  # LOW_RISK | MODERATE_RISK | HIGH_RISK
    explanation: str
    stress_summary: str = "none"

    @property
    def risk_reason(self) -> str:
        return self.explanation

    def to_result(self, calibration_version: str = CURRENT_CALIBRATION_VERSION) -> RiskAssessmentResult:
        return RiskAssessmentResult(
            risk_tier=self.risk_tier,
            safe_amount_p50=self.p50_safe_amount,
            safe_amount_p90=self.p90_safe_amount,
            minimum_balance_p50=self.p50_min_closing,
            minimum_balance_p90=self.p90_min_closing,
            headroom_p50=self.p50_headroom,
            headroom_p90=self.p90_headroom,
            risk_reason=self.explanation,
            stress_summary=self.stress_summary,
            calibration_version=calibration_version,
            p90_breach_detected=self.breach_under_p90 or self.post_payment_breach_p90,
        )


def classify_risk(
    state_p50: FinancialState,
    state_p90: FinancialState,
    requested_amount: Decimal,
    request_id: str = '',
    config: Optional[RiskCalibrationConfig] = None,
) -> RiskProfile:
    """
    Computes dual-track solvency metrics and assigns risk tier:
    - LOW_RISK: p90_safe_amount >= requested_amount (robust under stress)
    - MODERATE_RISK: p50_safe_amount >= requested_amount > p90_safe_amount (volatile buffer)
    - HIGH_RISK: p50_safe_amount < requested_amount (unaffordable even under baseline)
    """
    ledger_p50 = build_ledger(state_p50)
    ledger_p90 = build_ledger(state_p90)

    p50_min = ledger_p50.minimum_closing
    p90_min = ledger_p90.minimum_closing
    min_bal = state_p50.minimum_balance

    p50_safe = compute_safe_amount(state_p50, requested_amount)
    p90_safe = compute_safe_amount(state_p90, requested_amount)

    p50_headroom = p50_min - min_bal
    p90_headroom = p90_min - min_bal

    breach_p50 = p50_min < min_bal
    breach_p90 = p90_min < min_bal

    post_breach_p50 = (p50_headroom < requested_amount)
    post_breach_p90 = (p90_headroom < requested_amount)

    if p90_safe >= requested_amount:
        tier = 'LOW_RISK'
        expl = (
            f"Robust solvency: user maintains at least {p90_headroom:.2f} {state_p50.home_currency} "
            f"headroom above minimum balance even under 90th-percentile expenditure stress."
        )
    elif p50_safe >= requested_amount:
        tier = 'MODERATE_RISK'
        gap = requested_amount - p90_safe
        expl = (
            f"Spending volatility sensitivity: purchase is safe on expected cash flow (safe: {p50_safe:.2f}), "
            f"but a 90th-percentile variable expense spike creates a {gap:.2f} {state_p50.home_currency} deficit "
            f"against minimum balance."
        )
    else:
        tier = 'HIGH_RISK'
        expl = (
            f"Solvency deficit: requested amount exceeds safe immediate capacity under baseline conditions "
            f"(safe: {p50_safe:.2f} < requested {requested_amount:.2f})."
        )

    # Top category stress contributors
    factors = config.stress_factors if config else DEFAULT_P90_STRESS_FACTORS
    diff_by_cat: Dict[str, Decimal] = {}
    for item50, item90 in zip(state_p50.recurring_debits, state_p90.recurring_debits):
        diff = abs(item90.amount) - abs(item50.amount)
        if diff > Decimal('0.001'):
            diff_by_cat[item50.category] = diff_by_cat.get(item50.category, Decimal('0')) + diff

    if diff_by_cat:
        top_cats = sorted(diff_by_cat.keys(), key=lambda c: diff_by_cat[c], reverse=True)[:3]
        summary_parts = []
        for c in top_cats:
            factor = factors.get(c, Decimal('1.000'))
            pct = (factor - Decimal('1.000')) * Decimal('100')
            summary_parts.append(f"{c}:+{pct:.1f}%")
        stress_summary = "|".join(summary_parts)
    else:
        stress_summary = "none"

    return RiskProfile(
        request_id=request_id,
        user_id=state_p50.user_id,
        currency=state_p50.home_currency,
        requested_amount=requested_amount,
        minimum_balance_to_keep=min_bal,
        p50_min_closing=p50_min,
        p90_min_closing=p90_min,
        p50_safe_amount=p50_safe,
        p90_safe_amount=p90_safe,
        p50_headroom=p50_headroom,
        p90_headroom=p90_headroom,
        breach_under_p50=breach_p50,
        breach_under_p90=breach_p90,
        post_payment_breach_p50=post_breach_p50,
        post_payment_breach_p90=post_breach_p90,
        risk_tier=tier,
        explanation=expl,
        stress_summary=stress_summary,
    )
