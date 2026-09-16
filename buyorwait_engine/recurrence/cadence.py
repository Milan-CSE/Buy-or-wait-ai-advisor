"""
buyorwait_engine/recurrence/cadence.py

Infers recurring cashflow streams and cadences from settled LifecycleEvent history.
Groupings:
  - Fixed categories: grouped by (category, direction, description_prefix)
  - Variable categories: grouped by (category, direction)
"""
from __future__ import annotations
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
import statistics
from typing import Dict, List, Optional

from buyorwait_engine.domain.state import (
    FIXED_CATEGORIES,
    LifecycleEvent,
    VARIABLE_CATEGORIES,
)
from buyorwait_engine.domain.enums import CashType


class RecurrenceClass(Enum):
    CONFIRMED_RECURRING = 'confirmed_recurring'
    STRONG_RECURRING    = 'strong_recurring'
    VARIABLE_PATTERN    = 'variable_pattern'
    ONE_TIME            = 'one_time'
    NONE                = 'none'


@dataclass
class RecurringStream:
    """Represents a single inferred recurring cashflow stream."""
    key: str
    category: str
    direction: str
    recurrence_class: RecurrenceClass
    cadence_days: Optional[float]
    cadence_std: Optional[float]
    day_of_month: Optional[int]
    typical_amount: Decimal             # per-occurrence amount
    amount_std: Optional[float]
    last_date: Optional[date]
    event_ids: List[str]
    flexibility: str
    minimum_allowed_amount: Optional[Decimal]
    settled_amounts: List[Decimal] = field(default_factory=list)
    settled_dates: List[date] = field(default_factory=list)
    aggregate_weekly: Optional[Decimal] = None
    aggregate_monthly: Optional[Decimal] = None


def _description_prefix(desc: str) -> str:
    """Normalise description for grouping."""
    words = desc.lower().strip().split()
    return ' '.join(words[:4])


def _median_decimal(vals: List[Decimal]) -> Decimal:
    if not vals:
        return Decimal('0')
    sorted_vals = sorted(vals)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2


def _trimmed_median(vals: List[Decimal], trim_pct: float = 0.2) -> Decimal:
    if len(vals) < 4:
        return _median_decimal(vals)
    sorted_vals = sorted(vals)
    n = len(sorted_vals)
    cut = max(1, int(n * trim_pct))
    trimmed = sorted_vals[cut: n - cut]
    return _median_decimal(trimmed) if trimmed else _median_decimal(vals)


def _infer_fixed_streams(
    events: List[LifecycleEvent],
    as_of_date: date,
) -> List[RecurringStream]:
    groups: Dict[str, List[LifecycleEvent]] = {}
    for ev in events:
        if ev.category in VARIABLE_CATEGORIES:
            continue
        if ev.cash_type not in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME,
                                 CashType.FUTURE_DEBIT, CashType.CONFIRMED_INCOME):
            continue
        prefix = _description_prefix(ev.description)
        key = f"{ev.category}|{ev.direction}|{prefix}"
        groups.setdefault(key, []).append(ev)

    return _build_streams_from_groups(groups, as_of_date)


def _infer_variable_streams(
    events: List[LifecycleEvent],
    as_of_date: date,
) -> List[RecurringStream]:
    groups: Dict[str, List[LifecycleEvent]] = {}
    for ev in events:
        if ev.category not in VARIABLE_CATEGORIES:
            continue
        if ev.cash_type not in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME,
                                 CashType.FUTURE_DEBIT, CashType.CONFIRMED_INCOME):
            continue
        key = f"{ev.category}|{ev.direction}"
        groups.setdefault(key, []).append(ev)

    return _build_variable_streams_from_groups(groups, as_of_date)


def _build_streams_from_groups(
    groups: Dict[str, List[LifecycleEvent]],
    as_of_date: date,
) -> List[RecurringStream]:
    streams = []
    for key, evs in groups.items():
        settled = sorted(
            [e for e in evs
             if e.cash_type in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME)
             and e.settlement_date is not None
             and e.settlement_date <= as_of_date],
            key=lambda e: e.settlement_date,
        )

        all_dates = [e.settlement_date for e in evs if e.settlement_date]
        last_date = max(all_dates) if all_dates else None
        settled_amounts = [e.amount_home for e in settled if e.amount_home > 0]
        n = len(settled)

        cadence_days = None
        cadence_std = None
        day_of_month = None

        if n >= 2:
            intervals = [
                (settled[i].settlement_date - settled[i - 1].settlement_date).days
                for i in range(1, n)
            ]
            cadence_days = float(statistics.median(intervals))
            cadence_std = float(statistics.stdev(intervals)) if len(intervals) >= 2 else 0.0

            doms = [e.settlement_date.day for e in settled]
            dom_counts = {}
            for d in doms:
                dom_counts[d] = dom_counts.get(d, 0) + 1
            most_common_dom = max(dom_counts, key=dom_counts.get)
            if dom_counts[most_common_dom] >= max(2, n // 2):
                day_of_month = most_common_dom

        typical_amount = _trimmed_median(settled_amounts) if settled_amounts else Decimal('0')
        amt_std = None
        if len(settled_amounts) >= 2:
            amt_std = float(statistics.stdev([float(a) for a in settled_amounts]))

        if n >= 4 and cadence_std is not None and cadence_std <= 5.0:
            rec_class = RecurrenceClass.CONFIRMED_RECURRING
        elif n >= 3 and cadence_std is not None and cadence_std <= 10.0:
            rec_class = RecurrenceClass.STRONG_RECURRING
        elif n >= 2:
            rec_class = RecurrenceClass.VARIABLE_PATTERN
        elif n == 1:
            rec_class = RecurrenceClass.ONE_TIME
        else:
            rec_class = RecurrenceClass.NONE

        most_recent = max(evs, key=lambda e: e.settlement_date or date.min)
        cat = most_recent.category
        direction = most_recent.direction

        streams.append(RecurringStream(
            key=key,
            category=cat,
            direction=direction,
            recurrence_class=rec_class,
            cadence_days=cadence_days,
            cadence_std=cadence_std,
            day_of_month=day_of_month,
            typical_amount=typical_amount,
            amount_std=amt_std,
            last_date=last_date,
            event_ids=[e.event_id for e in evs],
            flexibility=most_recent.flexibility,
            minimum_allowed_amount=most_recent.minimum_allowed_amount,
            settled_amounts=settled_amounts,
            settled_dates=[e.settlement_date for e in settled],
        ))

    return streams


def _build_variable_streams_from_groups(
    groups: Dict[str, List[LifecycleEvent]],
    as_of_date: date,
) -> List[RecurringStream]:
    streams = []
    for key, evs in groups.items():
        settled = sorted(
            [e for e in evs
             if e.cash_type in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME)
             and e.settlement_date is not None
             and e.settlement_date <= as_of_date],
            key=lambda e: e.settlement_date,
        )

        all_dates = [e.settlement_date for e in evs if e.settlement_date]
        last_date = max(all_dates) if all_dates else None
        settled_amounts = [e.amount_home for e in settled if e.amount_home > 0]
        n = len(settled)

        if not settled:
            continue

        first_date = min(e.settlement_date for e in settled)
        window_days = max(1, (as_of_date - first_date).days)
        total_spend = sum(settled_amounts)
        num_weeks = max(Decimal('1'), Decimal(window_days) / Decimal('7'))
        num_months = max(Decimal('1'), Decimal(window_days) / Decimal('30'))

        weekly_spend = (total_spend / num_weeks).quantize(Decimal('0.01'))
        monthly_spend = (total_spend / num_months).quantize(Decimal('0.01'))

        cadence_days = float(window_days / n) if n > 0 else 7.0
        typical_amount = weekly_spend

        if n >= 6 and window_days >= 60:
            rec_class = RecurrenceClass.CONFIRMED_RECURRING
        elif n >= 3 and window_days >= 30:
            rec_class = RecurrenceClass.STRONG_RECURRING
        elif n >= 2:
            rec_class = RecurrenceClass.VARIABLE_PATTERN
        else:
            rec_class = RecurrenceClass.ONE_TIME

        most_recent = max(evs, key=lambda e: e.settlement_date or date.min)

        streams.append(RecurringStream(
            key=key,
            category=most_recent.category,
            direction=most_recent.direction,
            recurrence_class=rec_class,
            cadence_days=cadence_days,
            cadence_std=None,
            day_of_month=None,
            typical_amount=typical_amount,
            amount_std=None,
            last_date=last_date,
            event_ids=[e.event_id for e in evs],
            flexibility=most_recent.flexibility,
            minimum_allowed_amount=most_recent.minimum_allowed_amount,
            settled_amounts=settled_amounts,
            settled_dates=[e.settlement_date for e in settled],
            aggregate_weekly=weekly_spend,
            aggregate_monthly=monthly_spend,
        ))

    return streams


def infer_recurring_streams(
    events: List[LifecycleEvent],
    as_of_date: date,
) -> List[RecurringStream]:
    """
    Infer all recurring streams for a user's events.
    Uses appropriate grouping strategy per category type.
    """
    fixed_streams = _infer_fixed_streams(events, as_of_date)
    variable_streams = _infer_variable_streams(events, as_of_date)
    return fixed_streams + variable_streams


def _next_day_of_month(after: date, day: int, approx_days: int) -> date:
    year = after.year
    month = after.month + 1
    if month > 12:
        month = 1
        year += 1
    max_day = calendar.monthrange(year, month)[1]
    actual_day = min(day, max_day)
    return date(year, month, actual_day)


def project_next_occurrences(
    stream: RecurringStream,
    from_date: date,
    to_date: date,
) -> List[date]:
    """
    Project future occurrence dates for a recurring stream.
    """
    if stream.recurrence_class in (RecurrenceClass.ONE_TIME, RecurrenceClass.NONE):
        return []
    if stream.last_date is None or stream.cadence_days is None:
        return []

    cadence = round(stream.cadence_days)
    if cadence <= 0:
        return []

    occurrences: List[date] = []
    next_dt = stream.last_date + timedelta(days=cadence)

    if stream.day_of_month and 25 <= stream.cadence_days <= 35:
        next_dt = _next_day_of_month(stream.last_date, stream.day_of_month, cadence)

    while next_dt <= to_date:
        if next_dt >= from_date:
            occurrences.append(next_dt)
        if stream.day_of_month and 25 <= stream.cadence_days <= 35:
            next_dt = _next_day_of_month(next_dt, stream.day_of_month, cadence)
        else:
            next_dt = next_dt + timedelta(days=cadence)

    return occurrences
