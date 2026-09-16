"""
buyorwait_engine/engine.py

High-level decision engine for evaluating purchase proposals against financial state.
Coordinates:
1. Deterministic candidate generation with spending optimization and 6-tier ranking (V2 foundation)
2. Dual-track P50/P90 solvency analysis (V3 empirical risk layer)
3. Risk policy integration (Default: shadow_audit_only)
4. Domain model output creation
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from buyorwait_engine.domain.enums import Verdict
from buyorwait_engine.domain.state import FinancialState
from buyorwait_engine.domain.models import (
    PurchaseProposal,
    DecisionResult,
    FinancialProfileInput,
    CashflowEventInput,
)
from buyorwait_engine.currency.fx import FXEngine
from buyorwait_engine.state.builder import build_financial_state_from_inputs
from buyorwait_engine.decision.safe_amount import compute_safe_amount
from buyorwait_engine.decision.earliest_date import find_earliest_full_payment_date
from buyorwait_engine.decision.spending import enumerate_spending_change_combos
from buyorwait_engine.decision.candidates import generate_candidates, Candidate
from buyorwait_engine.decision.ranker import make_decision, Decision
from buyorwait_engine.risk.config import RiskCalibrationConfig, CURRENT_CALIBRATION_VERSION
from buyorwait_engine.risk.stress_buffers import build_stressed_state
from buyorwait_engine.risk.classifier import classify_risk, RiskProfile
from buyorwait_engine.risk.policy import apply_risk_policy


def _derive_verdict(method: str, spending_changes: str, request_date: date, first_date: Optional[date]) -> str:
    if method == 'not_recommended':
        return Verdict.NOT_RECOMMENDED.value
    if method == 'wait':
        return Verdict.WAIT.value
    if method == 'full_payment':
        if spending_changes == 'none' and first_date == request_date:
            return Verdict.BUY.value
        return Verdict.SAFER_PAYMENT.value
    if method in ('installments', 'partial_payment'):
        return Verdict.SAFER_PAYMENT.value
    return Verdict.NOT_RECOMMENDED.value


def evaluate_purchase(
    state: FinancialState,
    purchase: PurchaseProposal,
    risk_config: Optional[RiskCalibrationConfig] = None,
    risk_policy: str = 'shadow_audit_only',
) -> DecisionResult:
    """
    Evaluates a purchase proposal against a prepared FinancialState.
    """
    req_amt = purchase.requested_amount
    req_dt = purchase.request_date
    comp_dt = purchase.desired_completion_date

    # 1. Baseline safe amount & earliest safe full date (without spending changes)
    safe_amount = compute_safe_amount(state, req_amt)
    earliest_full_date = find_earliest_full_payment_date(state, req_amt)

    # 2. Enumerate spending change combinations and generate candidate plans
    options = purchase.payment_options or []
    spending_combos = enumerate_spending_change_combos(state, max_actions=3)
    all_candidates: List[Candidate] = []

    for sc in spending_combos:
        safe_with_sc = compute_safe_amount(state, req_amt, sc)
        earliest_with_sc = find_earliest_full_payment_date(state, req_amt, sc)
        cands = generate_candidates(
            state=state,
            req_amount=req_amt,
            req_date=req_dt,
            completion_date=comp_dt,
            allows_partial=purchase.allows_partial_payment,
            payment_options=options,
            spending_changes=sc,
            safe_amount=safe_with_sc,
            earliest_full_date=earliest_with_sc,
        )
        all_candidates.extend(cands)

    # 3. Deterministic V2 Decision
    v2_decision = make_decision(
        request_id=purchase.request_id,
        state=state,
        all_candidates=all_candidates,
        requested_amount=req_amt,
        request_date=req_dt,
        completion_date=comp_dt,
        safe_amount_no_changes=safe_amount,
        earliest_full_date=earliest_full_date,
    )

    # 4. V3 Empirical Risk Layer
    stressed_state = build_stressed_state(state, risk_config)
    risk_prof = classify_risk(
        state_p50=state,
        state_p90=stressed_state,
        requested_amount=req_amt,
        request_id=purchase.request_id,
        config=risk_config,
    )

    # Stress candidates & decision for policy evaluation if policy is not shadow
    if risk_policy != 'shadow_audit_only':
        stressed_safe = compute_safe_amount(stressed_state, req_amt)
        stressed_earliest = find_earliest_full_payment_date(stressed_state, req_amt)
        stressed_combos = enumerate_spending_change_combos(stressed_state, max_actions=3)
        stressed_candidates: List[Candidate] = []
        for sc in stressed_combos:
            s_safe_sc = compute_safe_amount(stressed_state, req_amt, sc)
            s_earliest_sc = find_earliest_full_payment_date(stressed_state, req_amt, sc)
            cands = generate_candidates(
                state=stressed_state,
                req_amount=req_amt,
                req_date=req_dt,
                completion_date=comp_dt,
                allows_partial=purchase.allows_partial_payment,
                payment_options=options,
                spending_changes=sc,
                safe_amount=s_safe_sc,
                earliest_full_date=s_earliest_sc,
            )
            stressed_candidates.extend(cands)

        stressed_decision = make_decision(
            request_id=purchase.request_id,
            state=stressed_state,
            all_candidates=stressed_candidates,
            requested_amount=req_amt,
            request_date=req_dt,
            completion_date=comp_dt,
            safe_amount_no_changes=stressed_safe,
            earliest_full_date=stressed_earliest,
        )
        final_decision = apply_risk_policy(v2_decision, stressed_decision, risk_prof, policy=risk_policy)
    else:
        final_decision = v2_decision

    calib_ver = risk_config.version if risk_config else CURRENT_CALIBRATION_VERSION
    risk_res = risk_prof.to_result(calibration_version=calib_ver)

    first_date = final_decision.best_candidate.first_payment_date if final_decision.best_candidate else None
    verdict = _derive_verdict(
        final_decision.recommended_payment_method,
        final_decision.spending_changes_needed,
        req_dt,
        first_date,
    )

    return DecisionResult(
        request_id=purchase.request_id,
        verdict=verdict,
        amount_safe_to_pay=final_decision.amount_safe_to_pay,
        affordability_status=final_decision.affordability_status,
        recommended_payment_method=final_decision.recommended_payment_method,
        payment_plan=final_decision.payment_plan,
        earliest_date_for_full_payment=final_decision.earliest_date_for_full_payment,
        spending_changes_needed=final_decision.spending_changes_needed,
        decision_explanation=final_decision.decision_explanation,
        risk_assessment=risk_res,
        audit_metrics={
            'risk_tier': risk_prof.risk_tier,
            'p50_headroom': float(risk_prof.p50_headroom),
            'p90_headroom': float(risk_prof.p90_headroom),
            'stress_summary': risk_prof.stress_summary,
        }
    )


class BuyOrWaitEngine:
    """
    Stateful or configured facade for running purchase evaluations.
    """
    def __init__(
        self,
        risk_config: Optional[RiskCalibrationConfig] = None,
        risk_policy: str = 'shadow_audit_only',
        fx: Optional[FXEngine] = None,
    ):
        self.risk_config = risk_config or RiskCalibrationConfig()
        self.risk_policy = risk_policy
        self.fx = fx or FXEngine()

    def evaluate(
        self,
        profile: FinancialProfileInput,
        events: Sequence[CashflowEventInput],
        purchase: PurchaseProposal,
    ) -> DecisionResult:
        state = build_financial_state_from_inputs(
            profile=profile,
            events=events,
            as_of_date=purchase.request_date,
            request_id=purchase.request_id,
            fx=self.fx,
        )
        return evaluate_purchase(
            state=state,
            purchase=purchase,
            risk_config=self.risk_config,
            risk_policy=self.risk_policy,
        )
