"""
buyorwait_engine/forecast/ledger.py

Simulates a daily cashflow ledger over a forecast horizon (typically 90 days).
Evaluates closing balances, credits, debits, and computes the minimum closing balance.
All calculations use Decimal arithmetic.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from buyorwait_engine.domain.state import FinancialState, FORECAST_HORIZON_DAYS


@dataclass
class DayEntry:
    dt: date
    opening: Decimal
    credits: Decimal
    debits: Decimal
    payment: Decimal
    closing: Decimal

    @property
    def net(self) -> Decimal:
        return self.closing


@dataclass
class Ledger:
    start_date: date
    entries: List[DayEntry]
    minimum_closing: Decimal
    minimum_closing_date: date


def _build_daily_maps(
    state: FinancialState,
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
    extra_payments: Optional[Dict[date, Decimal]] = None,
) -> Tuple[Dict[date, Decimal], Dict[date, Decimal]]:
    """
    Build credit_map and debit_map: date -> total amount.
    """
    credit_map: Dict[date, Decimal] = {}
    debit_map: Dict[date, Decimal] = {}

    def add_credit(dt: date, amt: Decimal):
        if dt is None or amt <= 0:
            return
        credit_map[dt] = credit_map.get(dt, Decimal('0')) + amt

    def add_debit(dt: date, amt: Decimal):
        if dt is None:
            return
        mag = abs(amt)
        if mag <= 0:
            return
        debit_map[dt] = debit_map.get(dt, Decimal('0')) + mag

    # ---- Scheduled future debits ----
    for item in state.future_debits:
        if item.date is None:
            continue
        if spending_changes and item.event_id_for_change in spending_changes:
            change = spending_changes[item.event_id_for_change]
            if change is None:
                continue  # stopped
            else:
                add_debit(item.date, change)
        else:
            add_debit(item.date, abs(item.amount))

    # ---- Scheduled future income ----
    for item in state.future_income:
        if item.date is None:
            continue
        add_credit(item.date, item.amount)

    # ---- Recurring projected debits ----
    for item in state.recurring_debits:
        if item.date is None:
            continue
        if spending_changes and item.event_id_for_change in spending_changes:
            change = spending_changes[item.event_id_for_change]
            if change is None:
                continue  # stopped
            else:
                if '[daily burn]' in item.description:
                    eff_change = item.minimum_allowed_amount if item.minimum_allowed_amount is not None else change
                    add_debit(item.date, eff_change)
                else:
                    add_debit(item.date, change)
        else:
            add_debit(item.date, abs(item.amount))

    # ---- Recurring projected income ----
    for item in state.recurring_income:
        if item.date is None:
            continue
        add_credit(item.date, item.amount)

    # ---- Extra payments ----
    if extra_payments:
        for dt, amt in extra_payments.items():
            if amt > 0:
                add_debit(dt, amt)

    return credit_map, debit_map


def build_ledger(
    state: FinancialState,
    spending_changes: Optional[Dict[str, Optional[Decimal]]] = None,
    extra_payments: Optional[Dict[date, Decimal]] = None,
    end_date: Optional[date] = None,
) -> Ledger:
    """
    Build a daily ledger from a financial state.
    """
    credit_map, debit_map = _build_daily_maps(state, spending_changes, extra_payments)

    start = state.request_date
    end = end_date if end_date is not None else (start + timedelta(days=FORECAST_HORIZON_DAYS))

    balance = state.starting_balance
    entries: List[DayEntry] = []

    min_closing = balance
    min_date = start

    current = start
    while current <= end:
        credits = credit_map.get(current, Decimal('0'))
        debits = debit_map.get(current, Decimal('0'))
        payment = extra_payments.get(current, Decimal('0')) if extra_payments else Decimal('0')

        closing = balance + credits - debits

        entry = DayEntry(
            dt=current,
            opening=balance,
            credits=credits,
            debits=debits,
            payment=payment,
            closing=closing,
        )
        entries.append(entry)

        if closing < min_closing:
            min_closing = closing
            min_date = current

        balance = closing
        current += timedelta(days=1)

    return Ledger(
        start_date=start,
        entries=entries,
        minimum_closing=min_closing,
        minimum_closing_date=min_date,
    )


def get_balance_on(ledger: Ledger, dt: date) -> Optional[Decimal]:
    """Return the closing balance on a specific date, or None if out of range."""
    start = ledger.start_date
    idx = (dt - start).days
    if 0 <= idx < len(ledger.entries):
        return ledger.entries[idx].closing
    return None


def min_balance_from(ledger: Ledger, from_date: date) -> Decimal:
    """Return minimum closing balance from from_date to end of ledger."""
    start = ledger.start_date
    idx = max(0, (from_date - start).days)
    if idx >= len(ledger.entries):
        return Decimal('Inf')
    sub = ledger.entries[idx:]
    if not sub:
        return Decimal('Inf')
    return min(e.closing for e in sub)
