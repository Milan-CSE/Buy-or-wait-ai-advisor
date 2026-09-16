"""
buyorwait_engine/decision/candidates.py

Generates all eligible candidate payment plans for a purchase request:
1. full_payment (if user accepts it and it is solvent today)
2. installments (for each eligible seller payment option)
3. partial_payment (two payments: safe amount today + remainder on earliest safe date)
4. wait (single full payment on earliest safe date before completion deadline)
5. not_recommended (fallback)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from buyorwait_engine.domain.state import FinancialState
from buyorwait_engine.decision.safe_amount import is_plan_safe, compute_safe_amount
from buyorwait_engine.decision.earliest_date import find_earliest_full_payment_date


@dataclass
class Candidate:
    method: str                   # full_payment | partial_payment | installments | wait | not_recommended
    payment_option_id: Optional[str]
    payment_plan: Dict[date, Decimal]  # {date: amount}
    spending_changes: Dict[str, Optional[Decimal]]  # {event_id: None (stop) | Decimal (reduce_to)}
    total_payable: Decimal
    num_payments: int
    first_payment_date: Optional[date]
    last_payment_date: Optional[date]
    completes_by_deadline: bool
    is_feasible: bool
    feasibility_note: str = ''


def _max_installment_days(max_months: Optional[Decimal]) -> Optional[int]:
    if max_months is None:
        return None
    return int(max_months * 31)


def _option_final_date(option: Any) -> Optional[date]:
    if option.first_payment_date is None:
        return None
    if option.number_of_payments == 1:
        return option.first_payment_date
    freq = getattr(option, 'payment_frequency_days', None)
    if freq is None:
        return option.first_payment_date
    days_to_last = (option.number_of_payments - 1) * freq
    return option.first_payment_date + timedelta(days=days_to_last)


def _option_plan(option: Any) -> Dict[date, Decimal]:
    plan: Dict[date, Decimal] = {}
    if option.first_payment_date is None:
        return plan
    dt = option.first_payment_date
    freq = getattr(option, 'payment_frequency_days', None)
    amt = getattr(option, 'payment_amount', getattr(option, 'installment_amount', Decimal('0')))
    for i in range(option.number_of_payments):
        plan[dt] = plan.get(dt, Decimal('0')) + amt
        if freq and i < option.number_of_payments - 1:
            dt = dt + timedelta(days=freq)
    return plan


def generate_candidates(
    state: FinancialState,
    req_amount: Optional[Decimal] = None,
    req_date: Optional[date] = None,
    completion_date: Optional[date] = None,
    allows_partial: bool = True,
    dataset: Optional[Any] = None,
    request_id: str = "",
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
    earliest_full_date: Optional[date] = None,
    safe_amount: Optional[Decimal] = None,
    payment_options: Optional[Sequence[Any]] = None,
    requested_amount: Optional[Decimal] = None,
    request_date: Optional[date] = None,
    safe_amount_no_changes: Optional[Decimal] = None,
    allows_partial_payment: Optional[bool] = None,
) -> List[Candidate]:
    """
    Generate all eligible candidates for a purchase proposal.
    Accepts either in-memory payment_options or legacy dataset container.
    """
    # Harmonize argument aliases
    actual_amount = req_amount if req_amount is not None else requested_amount
    actual_req_date = req_date if req_date is not None else request_date
    actual_safe = safe_amount if safe_amount is not None else safe_amount_no_changes
    actual_partial = allows_partial_payment if allows_partial_payment is not None else allows_partial

    if actual_amount is None or actual_req_date is None:
        raise ValueError("req_amount and req_date are required")

    sc = spending_changes or {}
    candidates: List[Candidate] = []
    user_payment_methods = state.payment_methods

    if actual_safe is None:
        actual_safe = compute_safe_amount(state, actual_amount, sc)

    if earliest_full_date is None:
        earliest_full_date = find_earliest_full_payment_date(state, actual_amount, sc)

    max_inst_days = _max_installment_days(state.max_installment_months)

    # Resolve options from direct list or legacy dataset
    options: List[Any] = []
    if payment_options is not None:
        options = list(payment_options)
    elif dataset is not None and hasattr(dataset, 'payment_options'):
        options = dataset.payment_options.get(request_id, [])

    # ---- 1. full_payment ----
    if 'full_payment' in user_payment_methods:
        plan = {actual_req_date: actual_amount}
        feasible = (actual_safe >= actual_amount) and is_plan_safe(state, plan, sc)
        candidates.append(Candidate(
            method='full_payment',
            payment_option_id=None,
            payment_plan=plan,
            spending_changes=sc,
            total_payable=actual_amount,
            num_payments=1,
            first_payment_date=actual_req_date,
            last_payment_date=actual_req_date,
            completes_by_deadline=(actual_req_date <= completion_date) if completion_date else True,
            is_feasible=feasible,
            feasibility_note='' if feasible else 'Balance drops below minimum on pay day',
        ))

    # ---- 2. installments ----
    if 'installments' in user_payment_methods:
        for option in options:
            opt_method = getattr(option, 'payment_method', getattr(option, 'payment_type', ''))
            if opt_method not in ('installments', 'installment'):
                continue
            if option.first_payment_date is None:
                continue

            final_date = _option_final_date(option)

            # Exclude if duration exceeds max_installment_months
            if max_inst_days is not None and final_date is not None:
                duration_days = (final_date - option.first_payment_date).days
                if duration_days > max_inst_days:
                    continue

            plan = _option_plan(option)
            feasible = is_plan_safe(state, plan, sc)
            completes_by_dl = (final_date <= completion_date) if (final_date and completion_date) else True
            tot = getattr(option, 'total_payable_amount', getattr(option, 'total_amount', Decimal('0')))

            candidates.append(Candidate(
                method='installments',
                payment_option_id=option.payment_option_id,
                payment_plan=plan,
                spending_changes=sc,
                total_payable=tot,
                num_payments=option.number_of_payments,
                first_payment_date=option.first_payment_date,
                last_payment_date=final_date,
                completes_by_deadline=completes_by_dl,
                is_feasible=feasible,
                feasibility_note='' if feasible else 'Balance drops below minimum during installments',
            ))

    # ---- 3. partial_payment ----
    if actual_partial and ('partial_payment' in user_payment_methods):
        if Decimal('0') < actual_safe < actual_amount:
            remaining = actual_amount - actual_safe
            if earliest_full_date is not None and (completion_date is None or earliest_full_date <= completion_date):
                plan = {
                    actual_req_date: actual_safe,
                    earliest_full_date: remaining,
                }
                feasible = is_plan_safe(state, plan, sc)
                completes_by_dl = (earliest_full_date <= completion_date) if completion_date else True
                candidates.append(Candidate(
                    method='partial_payment',
                    payment_option_id=None,
                    payment_plan=plan,
                    spending_changes=sc,
                    total_payable=actual_amount,
                    num_payments=2,
                    first_payment_date=actual_req_date,
                    last_payment_date=earliest_full_date,
                    completes_by_deadline=completes_by_dl,
                    is_feasible=feasible,
                    feasibility_note='' if feasible else 'Second payment unsafe',
                ))

    # ---- 4. wait ----
    if 'full_payment' in user_payment_methods:
        if earliest_full_date is not None and earliest_full_date > actual_req_date:
            if completion_date is None or earliest_full_date <= completion_date:
                plan = {earliest_full_date: actual_amount}
                feasible = is_plan_safe(state, plan, sc)
                completes_by_dl = (earliest_full_date <= completion_date) if completion_date else True
                candidates.append(Candidate(
                    method='wait',
                    payment_option_id=None,
                    payment_plan=plan,
                    spending_changes=sc,
                    total_payable=actual_amount,
                    num_payments=1,
                    first_payment_date=earliest_full_date,
                    last_payment_date=earliest_full_date,
                    completes_by_deadline=completes_by_dl,
                    is_feasible=feasible,
                    feasibility_note='' if feasible else 'Wait date exceeds horizon',
                ))

    # ---- 5. not_recommended (fallback) ----
    candidates.append(Candidate(
        method='not_recommended',
        payment_option_id=None,
        payment_plan={},
        spending_changes=sc,
        total_payable=Decimal('0'),
        num_payments=0,
        first_payment_date=None,
        last_payment_date=None,
        completes_by_deadline=False,
        is_feasible=True,
        feasibility_note='Fallback: no safe payment plan found',
    ))

    return candidates
