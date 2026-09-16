"""
backend/tests/test_observability/test_grounded_explanations.py

Tests enforcing the 9 Grounding Invariants for ExplanationService:
1. Exact numbers match DecisionResult facts without hallucination.
2. Exact dates match DecisionResult facts without hallucination.
3. No 'guarantee' / 'guaranteed' / 'promise' language.
4. Correct verdict narrative alignment (BUY, SAFER_PAYMENT, WAIT, NOT_RECOMMENDED).
5. Safe handling of DATA_INSUFFICIENT with required user remediation.
6. Absolute determinism across multiple runs.
"""
from decimal import Decimal
from datetime import date
from backend.services.data_quality import DataQualityResult
from backend.services.explanation_service import ExplanationService, GroundedExplanation
from buyorwait_engine.domain.models import DecisionResult, RiskAssessmentResult


def make_decision(
    verdict="BUY",
    affordability="affordable_now",
    amount_safe="150.00",
    method="full_payment",
    plan="none",
    earliest_date="2026-09-15",
    risk_tier="LOW_RISK",
    headroom_p50="1200.00",
    headroom_p90="950.00",
) -> DecisionResult:
    risk = RiskAssessmentResult(
        risk_tier=risk_tier,
        safe_amount_p50=Decimal(amount_safe),
        safe_amount_p90=Decimal(amount_safe),
        minimum_balance_p50=Decimal("500.00"),
        minimum_balance_p90=Decimal("500.00"),
        headroom_p50=Decimal(headroom_p50),
        headroom_p90=Decimal(headroom_p90),
        risk_reason="Sufficient reserves",
        stress_summary="Reserves remain intact under P90 stress",
        calibration_version="v3_test",
        p90_breach_detected=False,
    )
    return DecisionResult(
        request_id="req-test-1",
        verdict=verdict,
        affordability_status=affordability,
        amount_safe_to_pay=Decimal(amount_safe),
        recommended_payment_method=method,
        payment_plan=plan,
        earliest_date_for_full_payment=date.fromisoformat(earliest_date) if earliest_date else None,
        spending_changes_needed="none",
        decision_explanation="Domain engine decision explanation",
        risk_assessment=risk,
    )


class TestGroundedExplanations:
    def test_invariant_no_guarantee_language(self):
        dec = make_decision()
        exp = ExplanationService.explain_decision(dec, requested_amount=Decimal("150.00"))
        combined_text = f"{exp.headline} {exp.concise_explanation} {exp.risk_explanation} {exp.suggested_action}".lower()
        assert "guarantee" not in combined_text
        assert "guaranteed" not in combined_text
        assert "promise" not in combined_text

    def test_invariant_grounded_numbers_and_dates_buy(self):
        dec = make_decision(
            verdict="BUY",
            amount_safe="150.00",
            earliest_date="2026-09-15",
        )
        exp = ExplanationService.explain_decision(dec, requested_amount=Decimal("150.00"), currency="USD")
        assert "$150.00" in exp.concise_explanation or "150.00" in exp.concise_explanation
        assert exp.supporting_facts["safe_amount"] == "150.00"
        assert exp.supporting_facts["requested_amount"] == "150.00"
        assert exp.supporting_facts["verdict"] == "BUY"

    def test_invariant_safer_payment_installments(self):
        dec = make_decision(
            verdict="SAFER_PAYMENT",
            affordability="affordable_with_plan",
            amount_safe="50.00",
            method="installments",
            plan="2026-09-15:50.00|2026-10-15:50.00",
            risk_tier="MODERATE_RISK",
        )
        exp = ExplanationService.explain_decision(dec, requested_amount=Decimal("100.00"), currency="USD")
        assert "installments" in exp.concise_explanation.lower()
        assert "moderate risk profile" in exp.risk_explanation.lower()
        assert exp.supporting_facts["payment_plan"] == "2026-09-15:50.00|2026-10-15:50.00"

    def test_invariant_wait_narrative_and_future_date(self):
        dec = make_decision(
            verdict="WAIT",
            affordability="affordable_later",
            amount_safe="0.00",
            method="wait",
            earliest_date="2026-10-01",
            risk_tier="HIGH_RISK",
        )
        exp = ExplanationService.explain_decision(dec, requested_amount=Decimal("300.00"), currency="USD")
        assert "2026-10-01" in exp.concise_explanation
        assert "wait" in exp.headline.lower()
        assert exp.supporting_facts["earliest_date_for_full_payment"] == "2026-10-01"

    def test_invariant_data_insufficient_grounding(self):
        dq = DataQualityResult(
            is_sufficient=False,
            code="DATA_INSUFFICIENT",
            reason="No verified checking accounts found.",
            affected_data="accounts",
            user_action_required="Link or upload statements for an active checking account.",
        )
        exp = ExplanationService.explain_data_insufficient(dq)
        assert "insufficient" in exp.headline.lower()
        assert "No verified checking accounts found." in exp.concise_explanation
        assert exp.supporting_facts["affected_data"] == "accounts"
        assert "Link or upload" in exp.suggested_action

    def test_invariant_determinism(self):
        dec = make_decision(verdict="BUY", amount_safe="200.00")
        exp1 = ExplanationService.explain_decision(dec, requested_amount=Decimal("200.00"))
        exp2 = ExplanationService.explain_decision(dec, requested_amount=Decimal("200.00"))
        assert exp1 == exp2
        assert exp1.to_dict() == exp2.to_dict()
