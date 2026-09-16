"""
v3/risk_engine/shadow_mode.py

Executes the V3 risk layer in SHADOW MODE alongside frozen V2:
1. Computes official V2 decision (unmodified baseline).
2. Computes P50 diagnostics & P90 stressed state.
3. Computes V3 P90 decision (how V2 decision engine decides under P90 stress).
4. Emits unified diagnostic with V2 decision intact + V3 risk annotations.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import sys, os
sys.path.insert(0, os.path.abspath('code'))

from data_loader import Dataset, Request
from currency import FXEngine
from financial_state import build_financial_state
from safe_amount import compute_safe_amount
from earliest_full_payment import find_earliest_full_payment_date
from spending_optimizer import enumerate_spending_change_combos
from candidates import generate_candidates, Candidate
from ranker import make_decision, Decision
from validator import validate_decision, coerce_decision

from v3.risk_engine.stress_buffers import build_stressed_state
from v3.risk_engine.risk_classifier import classify_risk, RiskProfile


@dataclass
class ShadowResult:
    request_id: str
    v2_decision: Decision
    v3_p90_decision: Decision
    risk_profile: RiskProfile
    differs: bool


def run_shadow_from_state(
    req: Request,
    state_p50: FinancialState,
    v2_dec: Decision,
    dataset: Dataset,
) -> ShadowResult:
    """Runs shadow P90 track given pre-computed V2 state and decision."""
    # 2. Build P90 stressed state
    state_p90 = build_stressed_state(state_p50)
    safe_base_p90 = compute_safe_amount(state_p90, req.requested_amount)
    earliest_p90 = find_earliest_full_payment_date(state_p90, req.requested_amount)

    combos_p90 = enumerate_spending_change_combos(state_p90, max_actions=3)
    cands_p90: List[Candidate] = []
    for sc in combos_p90:
        safe_sc = compute_safe_amount(state_p90, req.requested_amount, sc)
        earliest_sc = find_earliest_full_payment_date(state_p90, req.requested_amount, sc)
        cands = generate_candidates(
            state=state_p90, req_amount=req.requested_amount, req_date=req.request_date,
            completion_date=req.desired_completion_date, allows_partial=req.allows_partial_payment,
            dataset=dataset, request_id=req.request_id, spending_changes=sc,
            earliest_full_date=earliest_sc, safe_amount=safe_sc,
        )
        cands_p90.extend(cands)

    v3_p90_dec = make_decision(
        request_id=req.request_id, state=state_p90, all_candidates=cands_p90,
        requested_amount=req.requested_amount, request_date=req.request_date,
        completion_date=req.desired_completion_date, safe_amount_no_changes=safe_base_p90,
        earliest_full_date=earliest_p90,
    )
    v3_p90_dec = coerce_decision(v3_p90_dec, req.requested_amount)

    # 3. Classify risk
    profile = classify_risk(state_p50, state_p90, req.requested_amount, req.request_id)

    differs = (
        v2_dec.recommended_payment_method != v3_p90_dec.recommended_payment_method
        or v2_dec.affordability_status != v3_p90_dec.affordability_status
        or abs(v2_dec.amount_safe_to_pay - v3_p90_dec.amount_safe_to_pay) > Decimal('0.01')
    )

    return ShadowResult(
        request_id=req.request_id,
        v2_decision=v2_dec,
        v3_p90_decision=v3_p90_dec,
        risk_profile=profile,
        differs=differs,
    )


def run_shadow_request(
    req: Request,
    dataset: Dataset,
    fx: FXEngine,
) -> ShadowResult:
    """Runs a single request through frozen V2 and shadow V3 P90 track."""
    # 1. Build P50 state (official V2)
    state_p50 = build_financial_state(req.user_id, req.request_id, req.request_date, dataset, fx)
    safe_base_p50 = compute_safe_amount(state_p50, req.requested_amount)
    earliest_p50 = find_earliest_full_payment_date(state_p50, req.requested_amount)

    combos_p50 = enumerate_spending_change_combos(state_p50, max_actions=3)
    cands_p50: List[Candidate] = []
    for sc in combos_p50:
        safe_sc = compute_safe_amount(state_p50, req.requested_amount, sc)
        earliest_sc = find_earliest_full_payment_date(state_p50, req.requested_amount, sc)
        cands = generate_candidates(
            state=state_p50, req_amount=req.requested_amount, req_date=req.request_date,
            completion_date=req.desired_completion_date, allows_partial=req.allows_partial_payment,
            dataset=dataset, request_id=req.request_id, spending_changes=sc,
            earliest_full_date=earliest_sc, safe_amount=safe_sc,
        )
        cands_p50.extend(cands)

    v2_dec = make_decision(
        request_id=req.request_id, state=state_p50, all_candidates=cands_p50,
        requested_amount=req.requested_amount, request_date=req.request_date,
        completion_date=req.desired_completion_date, safe_amount_no_changes=safe_base_p50,
        earliest_full_date=earliest_p50,
    )
    v2_dec = coerce_decision(v2_dec, req.requested_amount)

    return run_shadow_from_state(req, state_p50, v2_dec, dataset)
