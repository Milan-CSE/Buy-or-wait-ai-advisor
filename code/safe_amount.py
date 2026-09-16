"""
safe_amount.py
Computes amount_safe_to_pay: the maximum amount x such that:
  0 <= x <= requested_amount
  After paying x on request_date, the entire 90-day trajectory
  stays >= minimum_balance_to_keep.

Uses a direct calculation:
  headroom = min_balance_across_90_days - minimum_balance
  amount_safe = clamp(headroom, 0, requested_amount)

The baseline ledger (no payments) must be built first.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Optional

from financial_state import FinancialState
from forecast import build_ledger, min_balance_from


def compute_safe_amount(
    state: FinancialState,
    requested_amount: Decimal,
    spending_changes: Optional[dict] = None,
) -> Decimal:
    """
    Return the largest amount safely payable on request_date.

    Steps:
    1. Build baseline ledger (no payments yet).
    2. Min balance across the 90-day window = ledger.minimum_closing.
    3. Headroom = min_balance - minimum_balance_to_keep.
    4. Clamp to [0, requested_amount].
    """
    baseline = build_ledger(state, spending_changes=spending_changes)
    headroom = baseline.minimum_closing - state.minimum_balance
    safe = max(Decimal('0'), min(requested_amount, headroom))
    return safe


def compute_safe_amount_if_paid_on(
    state: FinancialState,
    payment_date: date,
    requested_amount: Decimal,
    spending_changes: Optional[dict] = None,
) -> Decimal:
    """
    Return the largest amount safely payable on a specific payment_date
    (used for computing partial payment second installment).
    """
    # Build a ledger with no payment to see the balance just before
    baseline = build_ledger(state, spending_changes=spending_changes)

    # min from payment_date onwards (after paying full amount on that date)
    from forecast import min_balance_from
    min_after = min_balance_from(baseline, payment_date)

    # Headroom = min after that date - minimum_balance
    # But we need to account for the payment itself on that date
    # Find balance JUST BEFORE payment_date debits/credits
    from forecast import get_balance_on
    balance_on_day = get_balance_on(baseline, payment_date)
    if balance_on_day is None:
        return Decimal('0')

    # If we pay X on that day, remaining balance = balance_on_day - X
    # Then min of remaining trajectory must stay >= minimum_balance
    # So X <= balance_on_day - minimum_balance AND X <= min_after - minimum_balance
    headroom = min(
        balance_on_day - state.minimum_balance,
        min_after - state.minimum_balance
    )
    return max(Decimal('0'), min(requested_amount, headroom))


def is_plan_safe(
    state: FinancialState,
    payments: dict,  # {date: amount}
    spending_changes: Optional[dict] = None,
) -> bool:
    """
    Check if a payment plan (payments dict) keeps the balance >= minimum_balance
    throughout the payment schedule (with Decimal('0.01') epsilon tolerance).
    """
    if not payments:
        ledger = build_ledger(state, spending_changes=spending_changes)
        return ledger.minimum_closing >= state.minimum_balance - Decimal('0.01')

    plan_end = max(payments.keys())
    ledger = build_ledger(state, spending_changes=spending_changes, extra_payments=payments)
    min_during_plan = min(e.closing for e in ledger.entries if e.dt <= plan_end)
    return min_during_plan >= state.minimum_balance - Decimal('0.01')
