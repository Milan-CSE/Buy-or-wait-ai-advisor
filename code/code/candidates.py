"""
candidates.py
Generates all eligible candidate payment plans for a request.

Candidates:
  1. full_payment (if user accepts it)
  2. installments (for each eligible option from request_payment_options.csv)
  3. partial_payment (if user accepts it and request allows it)
  4. wait (if full payment becomes safe later and user accepts full_payment)
  5. not_recommended (fallback)

Each candidate carries:
- method: the payment method type
- payment_option_id: option id from dataset (None for full/partial/wait)
- payment_plan: {date: Decimal} payments dict
- spending_changes: dict of changes applied (None = no changes)
- total_payable: total amount paid including fees
- num_payments: number of payments
- first_payment_date: date of first payment
- completes_by_deadline: bool
- is_feasible: bool (passes 90-day safety check)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from data_loader import Dataset, PaymentOption
from financial_state import FinancialState
from forecast import build_ledger
from safe_amount import is_plan_safe, compute_safe_amount
from earliest_full_payment import find_earliest_full_payment_date


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
    return int(max_months * 31)  # conservative ceiling


def _option_final_date(option: PaymentOption) -> Optional[date]:
    """Compute the actual final payment date for an installment option."""
    if option.first_payment_date is None:
        return None
    if option.number_of_payments == 1:
        return option.first_payment_date
    if option.payment_frequency_days is None:
        return option.first_payment_date
    days_to_last = (option.number_of_payments - 1) * option.payment_frequency_days
    return option.first_payment_date + timedelta(days=days_to_last)


def _option_plan(option: PaymentOption) -> Dict[date, Decimal]:
    """Build {date: amount} payment map from a PaymentOption."""
    plan: Dict[date, Decimal] = {}
    if option.first_payment_date is None:
        return plan
    dt = option.first_payment_date
    for i in range(option.number_of_payments):
        plan[dt] = plan.get(dt, Decimal('0')) + option.payment_amount
        if option.payment_frequency_days and i < option.number_of_payments - 1:
            dt = dt + timedelta(days=option.payment_frequency_days)
    return plan


def generate_candidates(
    state: FinancialState,
    req_amount: Decimal,
    req_date: date,
    completion_date: date,
    allows_partial: bool,
    dataset: Dataset,
    request_id: str,
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
    earliest_full_date: Optional[date] = None,
    safe_amount: Optional[Decimal] = None,
) -> List[Candidate]:
    """
    Generate all eligible candidates for a request.

    spending_changes: pre-computed spending changes to apply (or None for no changes)
    earliest_full_date: pre-computed earliest safe date for full payment
    safe_amount: pre-computed safe amount today
    """
    sc = spending_changes or {}
    candidates: List[Candidate] = []
    payment_methods = state.payment_methods

    # Compute safe amount if not provided
    if safe_amount is None:
        safe_amount = compute_safe_amount(state, req_amount, sc)

    # Compute earliest full date if not provided
    if earliest_full_date is None:
        earliest_full_date = find_earliest_full_payment_date(state, req_amount, sc)

    max_inst_days = _max_installment_days(state.max_installment_months)

    options: List[PaymentOption] = dataset.payment_options.get(request_id, [])

    # ---- 1. full_payment ----
    if 'full_payment' in payment_methods:
        plan = {req_date: req_amount}
        feasible = (safe_amount >= req_amount) and is_plan_safe(state, plan, sc)
        candidates.append(Candidate(
            method='full_payment',
            payment_option_id=None,
            payment_plan=plan,
            spending_changes=sc,
            total_payable=req_amount,
            num_payments=1,
            first_payment_date=req_date,
            last_payment_date=req_date,
            completes_by_deadline=(req_date <= completion_date),
            is_feasible=feasible,
            feasibility_note='' if feasible else 'Balance drops below minimum on pay day',
        ))

    # ---- 2. installments ----
    if 'installments' in payment_methods:
        for option in options:
            if option.payment_method != 'installments':
                continue
            if option.first_payment_date is None:
                continue

            # Check max_installment_months
            final_date = _option_final_date(option)
            if final_date is None:
                continue

            if max_inst_days is not None:
                span_days = (final_date - option.first_payment_date).days
                if span_days > max_inst_days:
                    continue

            # Check deadline
            completes_by_dl = (final_date is not None and final_date <= completion_date)

            # Build payment plan
            plan = _option_plan(option)

            # Safety check
            feasible = is_plan_safe(state, plan, sc)
            note = ''
            if not feasible:
                note = 'Balance drops below minimum during installment period'

            candidates.append(Candidate(
                method='installments',
                payment_option_id=option.payment_option_id,
                payment_plan=plan,
                spending_changes=sc,
                total_payable=option.total_payable_amount,
                num_payments=option.number_of_payments,
                first_payment_date=option.first_payment_date,
                last_payment_date=final_date,
                completes_by_deadline=completes_by_dl,
                is_feasible=feasible,
                feasibility_note=note,
            ))

    # ---- 3. partial_payment ----
    if ('partial_payment' in payment_methods) and allows_partial:
        # Partial: first payment = safe_amount on req_date
        # Second payment = remaining on earliest_full_date
        if Decimal('0') < safe_amount < req_amount:
            remaining = req_amount - safe_amount
            if earliest_full_date is not None and earliest_full_date <= completion_date:
                plan = {
                    req_date: safe_amount,
                    earliest_full_date: remaining,
                }
                feasible = is_plan_safe(state, plan, sc)
                candidates.append(Candidate(
                    method='partial_payment',
                    payment_option_id=None,
                    payment_plan=plan,
                    spending_changes=sc,
                    total_payable=req_amount,
                    num_payments=2,
                    first_payment_date=req_date,
                    last_payment_date=earliest_full_date,
                    completes_by_deadline=(earliest_full_date <= completion_date),
                    is_feasible=feasible,
                    feasibility_note='' if feasible else 'Second payment unsafe',
                ))

    # ---- 4. wait ----
    if 'full_payment' in payment_methods:
        if earliest_full_date is not None and earliest_full_date > req_date:
            if earliest_full_date <= completion_date:
                plan = {earliest_full_date: req_amount}
                feasible = is_plan_safe(state, plan, sc)
                candidates.append(Candidate(
                    method='wait',
                    payment_option_id=None,
                    payment_plan=plan,
                    spending_changes=sc,
                    total_payable=req_amount,
                    num_payments=1,
                    first_payment_date=earliest_full_date,
                    last_payment_date=earliest_full_date,
                    completes_by_deadline=(earliest_full_date <= completion_date),
                    is_feasible=feasible,
                    feasibility_note='' if feasible else 'Wait date exceeds horizon',
                ))

    # ---- 5. not_recommended (always included as fallback) ----
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
        feasibility_note='Fallback: no safe plan available',
    ))

    return candidates
