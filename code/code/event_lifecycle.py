"""
event_lifecycle.py
Resolves the lifecycle state of financial events.

Rules (from spec §6.3 and §4 Financial Semantics):
- settled: cash transaction completed, counts in history
- pending debit: MUST be reserved against balance immediately
- pending credit: do NOT count as available cash
- scheduled credit (salary): count on settlement_date
- scheduled debit: count as committed future obligation
- cancelled / failed: void, do not count
- unrealized (non_cash direction): never liquid cash; excluded from cashflow

linked_event_id:
- When event B links to event A via linked_event_id, B represents a
  later lifecycle stage. Prefer B's status over A.
- If B cancels A (B.status == 'cancelled' and B is the amendment),
  treat the pair as void.
- We do NOT hard-ban event A when B exists - instead we track and deduplicate:
  the lifecycle terminal state determines cashflow inclusion.

This module returns a cleaned list of LifecycleEvent objects for a user.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Set

from data_loader import Dataset, FinancialEvent
from currency import FXEngine
from evidence import get_image_amount


class CashType(Enum):
    IMMEDIATE_DEBIT   = 'immediate_debit'    # reserve immediately (pending/settled debit)
    FUTURE_DEBIT      = 'future_debit'        # confirmed future obligation (scheduled)
    SETTLED_INCOME    = 'settled_income'      # settled credit (historical)
    CONFIRMED_INCOME  = 'confirmed_income'    # scheduled credit (salary)
    NON_CASH          = 'non_cash'            # investment valuation etc – ignore
    VOID              = 'void'                # cancelled / failed / pending credit / unrealized


@dataclass
class LifecycleEvent:
    event_id: str
    user_id: str
    category: str
    description: str
    event_type: str
    direction: str
    original_status: str
    settlement_date: Optional[date]
    event_date: Optional[date]
    amount_home: Decimal                   # amount already converted to home currency
    original_currency: str
    cash_type: CashType
    flexibility: str
    minimum_allowed_amount: Optional[Decimal]
    linked_event_id: Optional[str]


def _effective_amount(event: FinancialEvent, home_currency: str, fx: FXEngine) -> Decimal:
    """
    Return event amount in home currency.
    Uses image manifest for events with missing amounts.
    """
    amount = event.amount
    if amount is None:
        fact = get_image_amount(event.event_id)
        if fact is None:
            # Cannot resolve - treat as 0 with warning
            return Decimal('0')
        amount = fact.verified_amount
        currency = fact.currency
    else:
        currency = event.currency

    if currency == home_currency:
        return amount

    settle_dt = event.settlement_date or event.event_date
    if settle_dt is None:
        return amount  # can't convert without date; skip FX

    try:
        return fx.to_home(amount, currency, home_currency, settle_dt)
    except Exception:
        # FX missing - return raw amount (diagnostics will flag it)
        return amount


def resolve_user_events(
    user_id: str,
    dataset: Dataset,
    fx: FXEngine,
) -> List[LifecycleEvent]:
    """
    Resolve all events for a user into typed LifecycleEvent objects.
    Handles lifecycle deduplication via linked_event_id chains.
    """
    raw_events: List[FinancialEvent] = dataset.events_by_user.get(user_id, [])
    profile = dataset.profiles.get(user_id)
    if not profile:
        return []

    home_currency = profile.home_currency

    # Build linked-event map: event_id -> event
    event_map: Dict[str, FinancialEvent] = {e.event_id: e for e in raw_events}

    # Identify events that are superseded by a later lifecycle event
    # (i.e., events that appear as linked_event_id of another event)
    superseded_ids: Set[str] = set()
    for e in raw_events:
        if e.linked_event_id and e.linked_event_id in event_map:
            # e supersedes e.linked_event_id
            # We mark the original as superseded only if the new event
            # represents a terminal (resolved) state
            orig = event_map[e.linked_event_id]
            # If the linking event is a valuation/non-cash update or refund,
            # we suppress the original to avoid double-counting
            if e.direction == 'non_cash' or e.event_type in ('refund', 'investment_valuation', 'investment_sale'):
                superseded_ids.add(e.linked_event_id)
            # If the linking event is a settled replacement of a pending/scheduled
            elif e.status in ('settled', 'cancelled', 'failed') and orig.status in ('pending', 'scheduled'):
                superseded_ids.add(e.linked_event_id)

    lifecycle_events: List[LifecycleEvent] = []

    for e in raw_events:
        if e.event_id in superseded_ids:
            continue  # skip original - lifecycle replaced by later event

        # Determine cash type
        cash_type = _classify_cash_type(e)

        if cash_type == CashType.VOID:
            continue

        amount_home = _effective_amount(e, home_currency, fx)

        lifecycle_events.append(LifecycleEvent(
            event_id=e.event_id,
            user_id=e.user_id,
            category=e.category,
            description=e.description,
            event_type=e.event_type,
            direction=e.direction,
            original_status=e.status,
            settlement_date=e.settlement_date,
            event_date=e.event_date,
            amount_home=amount_home,
            original_currency=e.currency,
            cash_type=cash_type,
            flexibility=e.flexibility,
            minimum_allowed_amount=e.minimum_allowed_amount,
            linked_event_id=e.linked_event_id,
        ))

    return lifecycle_events


def _classify_cash_type(e: FinancialEvent) -> CashType:
    """Classify event into a cashflow type."""

    # Non-cash direction always excluded from liquid cash
    if e.direction == 'non_cash':
        return CashType.NON_CASH

    # Void statuses
    if e.status in ('cancelled', 'failed'):
        return CashType.VOID

    # Unrealized investment value
    if e.status == 'unrealized':
        return CashType.NON_CASH

    # Pending events
    if e.status == 'pending':
        if e.direction == 'debit':
            return CashType.IMMEDIATE_DEBIT   # reserve now
        else:
            return CashType.VOID              # pending credit - do not count

    # Settled events
    if e.status == 'settled':
        if e.direction == 'debit':
            return CashType.IMMEDIATE_DEBIT   # historical settled debit
        else:
            return CashType.SETTLED_INCOME    # historical settled credit

    # Scheduled events
    if e.status == 'scheduled':
        if e.direction == 'debit':
            return CashType.FUTURE_DEBIT
        else:
            return CashType.CONFIRMED_INCOME

    # Fallback
    return CashType.VOID
