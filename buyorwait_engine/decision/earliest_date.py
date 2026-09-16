"""
buyorwait_engine/decision/earliest_date.py

Scans the 90-day forecast window to find the first calendar date on which paying
the full requested amount in one single lump sum preserves downstream solvency
without breaching minimum_balance_to_keep.
"""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional

from buyorwait_engine.domain.state import FinancialState
from buyorwait_engine.forecast.ledger import build_ledger


def find_earliest_full_payment_date(
    state: FinancialState,
    requested_amount: Decimal,
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
) -> Optional[date]:
    """
    Return the first date in [request_date, request_date + 90] on which
    paying requested_amount keeps the trajectory >= minimum_balance.
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
