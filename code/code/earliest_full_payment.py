"""
earliest_full_payment.py
Finds the earliest date within the 90-day window when paying the
requested_amount as a single full payment would keep the entire
remaining balance trajectory >= minimum_balance_to_keep.

Does NOT consider spending changes.
Does NOT require the user to accept full_payment as a method -
this is a financial capacity measure, independent of preferences.

Algorithm:
For each candidate date D from request_date to request_date + 90:
  Build a ledger with extra_payments = {D: requested_amount}
  If minimum closing balance >= minimum_balance_to_keep: D is safe.
  Return the first such D.

If none found: return None.
"""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from financial_state import FinancialState
from forecast import build_ledger


def find_earliest_full_payment_date(
    state: FinancialState,
    requested_amount: Decimal,
    spending_changes: Optional[dict] = None,
) -> Optional[date]:
    """
    Return the first date in [request_date, request_date + 90] on which
    paying requested_amount keeps the trajectory above minimum_balance.

    Returns None if no such date exists.
    """
    start = state.request_date
    end = start + timedelta(days=90)

    current = start
    while current <= end:
        payments = {current: requested_amount}
        ledger = build_ledger(state, spending_changes=spending_changes, extra_payments=payments)
        if ledger.minimum_closing >= state.minimum_balance:
            return current
        current += timedelta(days=1)

    return None
