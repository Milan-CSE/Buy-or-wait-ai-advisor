"""
buyorwait_engine/state/builder.py

Pure in-memory constructor for FinancialState from structured domain inputs.
Decoupled completely from CSV files, data loaders, and dataset directories.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Set

from buyorwait_engine.domain.models import FinancialProfileInput, CashflowEventInput
from buyorwait_engine.domain.state import (
    FinancialState,
    ScheduledItem,
    LifecycleEvent,
    FORECAST_HORIZON_DAYS,
    FIXED_CATEGORIES,
    VARIABLE_CATEGORIES,
    SALARY_TERMINATION_KEYWORDS,
)
from buyorwait_engine.domain.enums import CashType
from buyorwait_engine.currency.fx import FXEngine
from buyorwait_engine.recurrence.cadence import infer_recurring_streams, RecurringStream


def _classify_cash_type(e: CashflowEventInput) -> CashType:
    """Classify event into a cashflow type based on status and direction."""
    if e.direction == 'non_cash':
        return CashType.NON_CASH
    if e.status in ('cancelled', 'failed'):
        return CashType.VOID
    if e.status == 'unrealized':
        return CashType.NON_CASH
    if e.status == 'pending':
        if e.direction == 'debit':
            return CashType.IMMEDIATE_DEBIT
        return CashType.VOID
    if e.status == 'settled':
        if e.direction == 'debit':
            return CashType.IMMEDIATE_DEBIT
        return CashType.SETTLED_INCOME
    if e.status == 'scheduled':
        if e.direction == 'debit':
            return CashType.FUTURE_DEBIT
        return CashType.CONFIRMED_INCOME
    return CashType.VOID


def _convert_to_home(
    amount: Decimal,
    currency: str,
    home_currency: str,
    dt: Optional[date],
    fx: Optional[FXEngine],
) -> Decimal:
    if currency == home_currency or fx is None:
        return amount
    if dt is None:
        return amount
    try:
        return fx.to_home(amount, currency, home_currency, dt)
    except Exception:
        return amount


def resolve_events(
    events: Sequence[CashflowEventInput],
    home_currency: str,
    fx: Optional[FXEngine] = None,
) -> List[LifecycleEvent]:
    """Resolve lifecycle deduplication and convert currencies."""
    event_map: Dict[str, CashflowEventInput] = {e.event_id: e for e in events}
    superseded_ids: Set[str] = set()

    for e in events:
        if e.linked_event_id and e.linked_event_id in event_map:
            orig = event_map[e.linked_event_id]
            if e.direction == 'non_cash' or e.event_type in ('refund', 'investment_valuation', 'investment_sale'):
                superseded_ids.add(e.linked_event_id)
            elif e.status in ('settled', 'cancelled', 'failed') and orig.status in ('pending', 'scheduled'):
                superseded_ids.add(e.linked_event_id)

    out: List[LifecycleEvent] = []
    for e in events:
        if e.event_id in superseded_ids:
            continue
        ctype = _classify_cash_type(e)
        if ctype == CashType.VOID:
            continue

        ref_date = e.settlement_date or e.event_date
        amt_home = _convert_to_home(e.amount, e.currency, home_currency, ref_date, fx)

        out.append(LifecycleEvent(
            event_id=e.event_id,
            user_id=e.user_id,
            category=e.category,
            description=e.description,
            event_type=e.event_type,
            direction=e.direction,
            original_status=e.status,
            settlement_date=e.settlement_date,
            event_date=e.event_date,
            amount_home=amt_home,
            original_currency=e.currency,
            cash_type=ctype,
            flexibility=e.flexibility,
            minimum_allowed_amount=e.minimum_allowed_amount,
            linked_event_id=e.linked_event_id,
        ))
    return out


def _project_fixed_category(
    events: List[LifecycleEvent],
    category: str,
    as_of_date: date,
    horizon_end: date,
) -> List[ScheduledItem]:
    cat_events = [
        e for e in events
        if e.category == category
        and e.cash_type == CashType.IMMEDIATE_DEBIT
        and e.original_status == 'settled'
        and e.settlement_date and e.settlement_date <= as_of_date
    ]
    if not cat_events:
        return []

    cat_events.sort(key=lambda e: e.settlement_date)
    recent = cat_events[-6:]

    if len(recent) < 2:
        return []

    intervals = [(recent[i].settlement_date - recent[i-1].settlement_date).days for i in range(1, len(recent))]
    avg_interval = sum(intervals) / len(intervals)

    if not (20 <= avg_interval <= 40):
        return []

    dom_counts: Dict[int, int] = {}
    for e in recent:
        d = e.settlement_date.day
        dom_counts[d] = dom_counts.get(d, 0) + 1
    typical_dom = max(dom_counts.items(), key=lambda x: x[1])[0]

    amounts = sorted([abs(e.amount_home) for e in recent])
    typical_amt = amounts[len(amounts) // 2]

    source_ev = recent[-1]
    flex = source_ev.flexibility
    min_allowed = source_ev.minimum_allowed_amount
    ev_for_change = source_ev.event_id

    items = []
    cur_yr = as_of_date.year
    cur_mo = as_of_date.month

    while True:
        max_d = calendar.monthrange(cur_yr, cur_mo)[1]
        dt = date(cur_yr, cur_mo, min(typical_dom, max_d))
        if dt > horizon_end:
            break
        if dt > as_of_date:
            items.append(ScheduledItem(
                event_id=None,
                date=dt,
                amount=-typical_amt,
                category=category,
                description=f'[recurring] {category}',
                source='recurring',
                flexibility=flex,
                minimum_allowed_amount=min_allowed,
                event_id_for_change=ev_for_change,
            ))
        cur_mo += 1
        if cur_mo > 12:
            cur_mo = 1
            cur_yr += 1

    return items


def _project_variable_category(
    events: List[LifecycleEvent],
    category: str,
    as_of_date: date,
    horizon_end: date,
    use_daily_burn: bool = True,
) -> List[ScheduledItem]:
    lookback_start = as_of_date - timedelta(days=90)
    cat_events = [
        e for e in events
        if e.category == category
        and e.cash_type == CashType.IMMEDIATE_DEBIT
        and e.original_status == 'settled'
        and e.settlement_date
        and lookback_start <= e.settlement_date <= as_of_date
    ]
    if not cat_events:
        return []

    source_ev = sorted(cat_events, key=lambda e: e.settlement_date)[-1]
    flex = source_ev.flexibility
    min_allowed = source_ev.minimum_allowed_amount
    ev_for_change = source_ev.event_id

    total_spent = sum(abs(e.amount_home) for e in cat_events)
    lookback_days = Decimal(str((as_of_date - lookback_start).days))
    daily_rate = total_spent / lookback_days if lookback_days > 0 else Decimal('0')

    if daily_rate <= Decimal('0'):
        return []

    items = []
    if use_daily_burn:
        cur = as_of_date + timedelta(days=1)
        while cur <= horizon_end:
            items.append(ScheduledItem(
                event_id=None,
                date=cur,
                amount=-daily_rate,
                category=category,
                description=f'[recurring daily] {category}',
                source='recurring',
                flexibility=flex,
                minimum_allowed_amount=min_allowed,
                event_id_for_change=ev_for_change,
            ))
            cur += timedelta(days=1)
    else:
        weekly_rate = daily_rate * Decimal('7')
        cur = as_of_date + timedelta(days=7)
        while cur <= horizon_end:
            items.append(ScheduledItem(
                event_id=None,
                date=cur,
                amount=-weekly_rate,
                category=category,
                description=f'[recurring weekly] {category}',
                source='recurring',
                flexibility=flex,
                minimum_allowed_amount=min_allowed,
                event_id_for_change=ev_for_change,
            ))
            cur += timedelta(days=7)

    return items


def _project_salary(
    events: List[LifecycleEvent],
    as_of_date: date,
    horizon_end: date,
    scheduled_dates: Set[date],
) -> List[ScheduledItem]:
    salary_all = sorted(
        [e for e in events
         if e.category == 'salary'
         and e.cash_type in (CashType.CONFIRMED_INCOME, CashType.SETTLED_INCOME)
         and e.settlement_date
         and e.amount_home > 0
         and not any(w in (e.description or '').lower() for w in ['commission', 'bonus', 'komisi', 'arrears', 'one-time', 'adjustment'])],
        key=lambda e: e.settlement_date,
    )

    if len(salary_all) < 2:
        return []

    last_ev = salary_all[-1]
    desc = (last_ev.description or '').lower()
    if any(k in desc for k in SALARY_TERMINATION_KEYWORDS):
        return []

    recent = salary_all[-6:]
    intervals = [(recent[i].settlement_date - recent[i-1].settlement_date).days for i in range(1, len(recent))]
    avg_interval = sum(intervals) / len(intervals)
    if avg_interval <= 0:
        return []

    scheduled_salary = [e for e in salary_all if e.cash_type == CashType.CONFIRMED_INCOME]
    if scheduled_salary:
        typical_amount = max(scheduled_salary, key=lambda e: e.settlement_date).amount_home
    else:
        amounts = sorted([e.amount_home for e in recent])
        typical_amount = amounts[len(amounts) // 2]

    last_date = salary_all[-1].settlement_date

    dom_counts: Dict[int, int] = {}
    for e in recent:
        dom = e.settlement_date.day
        dom_counts[dom] = dom_counts.get(dom, 0) + 1
    most_common_dom, dom_freq = max(dom_counts.items(), key=lambda x: x[1])
    is_monthly = (25 <= avg_interval <= 35) or (dom_freq >= 2 and dom_freq / len(recent) >= 0.5)

    items = []
    if is_monthly:
        cur_yr = last_date.year
        cur_mo = last_date.month
        while True:
            cur_mo += 1
            if cur_mo > 12:
                cur_mo = 1
                cur_yr += 1
            max_d = calendar.monthrange(cur_yr, cur_mo)[1]
            dt = date(cur_yr, cur_mo, min(most_common_dom, max_d))
            if dt > horizon_end:
                break
            if dt > as_of_date and dt not in scheduled_dates:
                items.append(ScheduledItem(
                    event_id=None,
                    date=dt,
                    amount=typical_amount,
                    category='salary',
                    description='[recurring] salary',
                    source='recurring',
                ))
    else:
        next_dt = last_date + timedelta(days=round(avg_interval))
        while next_dt <= horizon_end:
            if next_dt > as_of_date and next_dt not in scheduled_dates:
                items.append(ScheduledItem(
                    event_id=None,
                    date=next_dt,
                    amount=typical_amount,
                    category='salary',
                    description='[recurring] salary',
                    source='recurring',
                ))
            next_dt += timedelta(days=round(avg_interval))

    return items


def build_financial_state_from_inputs(
    profile: FinancialProfileInput,
    events: Sequence[CashflowEventInput],
    as_of_date: date,
    request_id: str = '',
    fx: Optional[FXEngine] = None,
    use_daily_burn: bool = True,
) -> FinancialState:
    """
    Constructs FinancialState directly from in-memory profile and events.
    Zero disk access, 100% deterministic and isolated.
    """
    horizon_end = as_of_date + timedelta(days=FORECAST_HORIZON_DAYS)
    resolved = resolve_events(events, profile.home_currency, fx)

    pending_debit_total = Decimal('0')
    for ev in resolved:
        if ev.cash_type == CashType.IMMEDIATE_DEBIT and ev.original_status == 'pending':
            pending_debit_total += ev.amount_home
    starting_balance = profile.current_available_balance - pending_debit_total

    future_debits: List[ScheduledItem] = []
    future_income: List[ScheduledItem] = []

    for ev in resolved:
        settle_dt = ev.settlement_date
        if settle_dt is None or settle_dt <= as_of_date or settle_dt > horizon_end:
            continue
        if ev.cash_type == CashType.FUTURE_DEBIT:
            future_debits.append(ScheduledItem(
                event_id=ev.event_id,
                date=settle_dt,
                amount=-ev.amount_home,
                category=ev.category,
                description=ev.description,
                source='scheduled',
                flexibility=ev.flexibility,
                minimum_allowed_amount=ev.minimum_allowed_amount,
                event_id_for_change=ev.event_id,
            ))
        elif ev.cash_type == CashType.CONFIRMED_INCOME:
            future_income.append(ScheduledItem(
                event_id=ev.event_id,
                date=settle_dt,
                amount=ev.amount_home,
                category=ev.category,
                description=ev.description,
                source='scheduled',
            ))

    recurring_debits: List[ScheduledItem] = []
    recurring_income: List[ScheduledItem] = []

    for cat in FIXED_CATEGORIES:
        sched_dates = set(it.date for it in future_debits if it.category == cat)
        projected = _project_fixed_category(resolved, cat, as_of_date, horizon_end)
        for item in projected:
            if item.date not in sched_dates:
                recurring_debits.append(item)

    for cat in VARIABLE_CATEGORIES:
        projected = _project_variable_category(
            resolved, cat, as_of_date, horizon_end, use_daily_burn=use_daily_burn
        )
        recurring_debits.extend(projected)

    scheduled_income_dates = set(it.date for it in future_income if it.category == 'salary')
    salary_items = _project_salary(resolved, as_of_date, horizon_end, scheduled_income_dates)
    recurring_income.extend(salary_items)

    recurring_streams = infer_recurring_streams(resolved, as_of_date=as_of_date)

    return FinancialState(
        user_id=profile.user_id,
        request_id=request_id,
        request_date=as_of_date,
        home_currency=profile.home_currency,
        starting_balance=starting_balance,
        balance_before_pending=profile.current_available_balance,
        minimum_balance=profile.minimum_balance_to_keep,
        pending_debit_total=pending_debit_total,
        protected_categories=list(profile.protected_categories),
        reducible_categories=list(profile.reducible_categories),
        stoppable_categories=list(profile.stoppable_categories),
        payment_methods=list(profile.payment_methods),
        max_installment_months=profile.max_installment_months,
        lifecycle_events=resolved,
        future_debits=future_debits,
        future_income=future_income,
        recurring_debits=recurring_debits,
        recurring_income=recurring_income,
        recurring_streams=recurring_streams,
        message_amendments=[],
    )
