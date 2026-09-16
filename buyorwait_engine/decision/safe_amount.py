"""
buyorwait_engine/decision/safe_amount.py

Calculates maximal safe payment amounts and verifies payment plan safety against
the user's 90-day cashflow ledger and minimum balance constraint.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Dict, Optional

from buyorwait_engine.domain.state import FinancialState
from buyorwait_engine.forecast.ledger import (
    build_ledger,
    get_balance_on,
    min_balance_from,
)


def compute_safe_amount(
    state: FinancialState,
    requested_amount: Decimal,
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
) -> Decimal:
    """
    Return the largest amount safely payable on request_date.
    Formula: headroom = baseline.minimum_closing - state.minimum_balance
             safe = clamp(headroom, 0, requested_amount)
    """
    baseline = build_ledger(state, spending_changes=spending_changes)
    headroom = baseline.minimum_closing - state.minimum_balance
    safe = max(Decimal('0'), min(requested_amount, headroom))
    return safe


def compute_safe_amount_if_paid_on(
    state: FinancialState,
    payment_date: date,
    requested_amount: Decimal,
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
) -> Decimal:
    """
    Return the largest amount safely payable on a specific future date.
    Used for computing partial payment second tranches.
    """
    baseline = build_ledger(state, spending_changes=spending_changes)
    min_after = min_balance_from(baseline, payment_date)
    balance_on_day = get_balance_on(baseline, payment_date)
    if balance_on_day is None:
        return Decimal('0')

    headroom = min(
        balance_on_day - state.minimum_balance,
        min_after - state.minimum_balance,
    )
    return max(Decimal('0'), min(requested_amount, headroom))


def is_plan_safe(
    state: FinancialState,
    payments: Dict[date, Decimal],
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
) -> bool:
    """
    Check if a payment plan keeps the balance >= minimum_balance
    throughout the payment schedule (with Decimal('0.01') epsilon tolerance).
    """
    if not payments:
        ledger = build_ledger(state, spending_changes=spending_changes)
        return ledger.minimum_closing >= state.minimum_balance - Decimal('0.01')

    plan_end = max(payments.keys())
    ledger = build_ledger(state, spending_changes=spending_changes, extra_payments=payments)
    min_during_plan = min(e.closing for e in ledger.entries if e.dt <= plan_end)
    return min_during_plan >= state.minimum_balance - Decimal('0.01')
