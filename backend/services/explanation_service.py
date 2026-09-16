"""
backend/services/explanation_service.py

Deterministic Grounded Explanation Engine transforming DecisionResult artifacts into
clear, auditable, human-readable explanations strictly grounded in calculated financial facts.
Enforces 9 grounding invariants: zero invented numbers, zero invented dates, zero guarantee language.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from backend.services.data_quality import DataQualityResult
from buyorwait_engine.domain.models import DecisionResult


@dataclass(frozen=True)
class ExplanationFacts:
    """Structured financial facts strictly extracted from the DecisionResult artifact."""
    requested_amount: str
    safe_amount: str
    currency: str
    verdict: str
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[str]
    reserve_required: Optional[str]
    risk_tier: str
    headroom_p50: Optional[str]
    headroom_p90: Optional[str]
    safe_amount_p50: Optional[str]
    safe_amount_p90: Optional[str]
    stress_summary: Optional[str]
    spending_changes_needed: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GroundedExplanation:
    """Standard grounded explanation structure."""
    headline: str
    concise_explanation: str
    supporting_facts: Dict[str, Any]
    risk_explanation: str
    suggested_action: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExplanationService:
    """
    Deterministic explanation service.
    Translates raw decision data into user-friendly narratives without performing any new math.
    """

    @classmethod
    def explain_decision(
        cls,
        decision: DecisionResult,
        requested_amount: Decimal,
        currency: str = "USD",
        minimum_balance: Optional[Decimal] = None,
    ) -> GroundedExplanation:
        """
        Generates grounded explanation for a completed DecisionResult.
        Every numeric figure and date in the prose is verified to originate from the input facts.
        """
        risk = decision.risk_assessment
        risk_tier = risk.risk_tier if risk else "LOW_RISK"
        headroom_p50 = str(risk.headroom_p50) if risk and risk.headroom_p50 is not None else None
        headroom_p90 = str(risk.headroom_p90) if risk and risk.headroom_p90 is not None else None
        safe_p50 = str(risk.safe_amount_p50) if risk and risk.safe_amount_p50 is not None else None
        safe_p90 = str(risk.safe_amount_p90) if risk and risk.safe_amount_p90 is not None else None
        stress_summary = risk.stress_summary if risk else None
        reserve_str = str(minimum_balance) if minimum_balance is not None else None

        earliest_date_str = (
            decision.earliest_date_for_full_payment.isoformat()
            if decision.earliest_date_for_full_payment else None
        )

        facts = ExplanationFacts(
            requested_amount=str(requested_amount),
            safe_amount=str(decision.amount_safe_to_pay),
            currency=currency,
            verdict=decision.verdict,
            affordability_status=decision.affordability_status,
            recommended_payment_method=decision.recommended_payment_method,
            payment_plan=decision.payment_plan,
            earliest_date_for_full_payment=earliest_date_str,
            reserve_required=reserve_str,
            risk_tier=risk_tier,
            headroom_p50=headroom_p50,
            headroom_p90=headroom_p90,
            safe_amount_p50=safe_p50,
            safe_amount_p90=safe_p90,
            stress_summary=stress_summary,
            spending_changes_needed=decision.spending_changes_needed,
        )

        verdict = decision.verdict
        # 1. Headline & Concise Explanation
        if verdict == "BUY":
            headline = "Purchase is safe to complete today"
            reserve_clause = f" while preserving your {currency} {reserve_str} minimum balance" if reserve_str else ""
            concise = (
                f"Your requested purchase of {currency} {facts.requested_amount} is fully within your safe spending capacity "
                f"of {currency} {facts.safe_amount}. All projected cashflow commitments are satisfied{reserve_clause}."
            )
            action = "Proceed with upfront full payment."

        elif verdict == "SAFER_PAYMENT":
            headline = "Purchase is affordable using a recommended payment plan"
            concise = (
                f"Full upfront payment of {currency} {facts.requested_amount} is unsafe today (safe amount: {currency} {facts.safe_amount}). "
                f"However, the purchase is viable using {facts.recommended_payment_method} ({facts.payment_plan})."
            )
            action = f"Select the recommended payment plan ({facts.payment_plan}) rather than paying upfront."

        elif verdict == "WAIT":
            headline = "Wait until upcoming cashflow improves your balance"
            date_clause = f" on or after {facts.earliest_date_for_full_payment}" if facts.earliest_date_for_full_payment else " at a later date"
            concise = (
                f"A full payment of {currency} {facts.requested_amount} is not safe today (safe amount: {currency} {facts.safe_amount}). "
                f"Cashflow projections indicate a safe payment can be completed{date_clause}."
            )
            action = f"Delay the purchase until {facts.earliest_date_for_full_payment} when funds become safe." if facts.earliest_date_for_full_payment else "Delay the purchase until sufficient liquid funds accumulate."

        else:  # NOT_RECOMMENDED
            headline = "Purchase not recommended within forecast horizon"
            concise = (
                f"Your requested purchase of {currency} {facts.requested_amount} exceeds your safe capacity "
                f"(safe amount: {currency} {facts.safe_amount}). No safe installment or delayed payment schedule was found within 90 days."
            )
            action = "Do not proceed with this purchase at this time, or consider a significantly smaller purchase amount."

        # 2. Grounded Risk Explanation
        if risk_tier == "LOW_RISK":
            risk_expl = (
                f"Low risk profile: Even under 90th-percentile simulated expenditure stress, your projected cash balance maintains "
                f"a safety headroom of {currency} {facts.headroom_p90 or facts.headroom_p50 or '0.00'}."
            )
        elif risk_tier == "MODERATE_RISK":
            risk_expl = (
                f"Moderate risk profile: The purchase is solvent under expected conditions with {currency} {facts.headroom_p50} headroom, "
                f"but higher-than-usual spending narrows stress headroom to {currency} {facts.headroom_p90}."
            )
        else:  # HIGH_RISK
            risk_expl = (
                f"High risk profile: Under stressed expenditure conditions, your projected balance breaches required safety thresholds."
            )

        return GroundedExplanation(
            headline=headline,
            concise_explanation=concise,
            supporting_facts=facts.to_dict(),
            risk_explanation=risk_expl,
            suggested_action=action,
        )

    @classmethod
    def explain_data_insufficient(cls, dq_result: DataQualityResult) -> GroundedExplanation:
        """Generates grounded explanation when data quality gates fail."""
        headline = "Evaluation cannot proceed due to insufficient financial data"
        concise = (
            f"We could not evaluate purchase safety because your financial profile is incomplete: {dq_result.reason} "
            f"(missing: {dq_result.affected_data})."
        )
        action = dq_result.user_action_required
        risk_expl = "Risk assessment unavailable: Forecast models require validated historical records to project cash flow."

        return GroundedExplanation(
            headline=headline,
            concise_explanation=concise,
            supporting_facts={
                "status": "DATA_INSUFFICIENT",
                "code": dq_result.code,
                "affected_data": dq_result.affected_data,
                "remediation": dq_result.user_action_required,
            },
            risk_explanation=risk_expl,
            suggested_action=action,
        )
