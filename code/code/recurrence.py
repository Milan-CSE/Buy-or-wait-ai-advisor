"""
recurrence.py
Infers recurring cashflow streams from actual settled event history.

GROUPING STRATEGY:
  Fixed/subscription categories: group by (category, direction, description_prefix)
    Examples: rent, salary, utilities, debt_repayment, streaming, insurance
  Variable/discretionary categories: group by (category, direction) only
    Examples: groceries, transport, dining, shopping, healthcare

For variable categories, we treat all events in the category as ONE combined stream
with a weekly/periodic aggregate spend pattern.

Classification:
  CONFIRMED_RECURRING   - 4+ occurrences, tight cadence (<= 5-day std dev)
  STRONG_RECURRING      - 3+ occurrences, moderate cadence (<= 10-day std dev)
  VARIABLE_PATTERN      - 2-3 occurrences, wide cadence variation
  ONE_TIME              - single occurrence
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple

from event_lifecycle import LifecycleEvent, CashType


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
    # For variable categories: aggregate weekly/monthly amount
    aggregate_weekly: Optional[Decimal] = None
    aggregate_monthly: Optional[Decimal] = None


# Categories where all transactions are treated as ONE aggregated periodic stream
VARIABLE_CATEGORIES = frozenset([
    'groceries', 'transport', 'dining', 'shopping', 'healthcare',
    'entertainment', 'personal_care', 'clothing', 'fitness', 'miscellaneous',
    'travel', 'gifts', 'childcare', 'electronics',
])

# Categories where we group by description (subscription/fixed)
FIXED_CATEGORIES = frozenset([
    'rent', 'salary', 'utilities', 'debt_repayment', 'insurance', 'housing',
    'streaming', 'music_subscription', 'cloud_storage', 'delivery_membership',
    'education', 'investment', 'savings', 'tax',
])


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
    """
    For fixed categories: group by (category, direction, description_prefix).
    Each sub-group produces one stream.
    """
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
    """
    For variable categories: group by (category, direction) only.
    Treat all transactions in the category as one aggregate stream.

    The cadence here is computed by counting total occurrences over the observation
    window and dividing the window by the number of occurrences.

    The 'typical_amount' here represents the TOTAL spend per cadence period.
    """
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
    """Build RecurringStream objects from grouped fixed events."""
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
            cadence_days = sum(intervals) / len(intervals)
            cadence_std = statistics.stdev(intervals) if len(intervals) > 1 else 0.0
            if 25 <= cadence_days <= 35:
                dom_counts: Dict[int, int] = {}
                for e in settled:
                    dom = e.settlement_date.day
                    dom_counts[dom] = dom_counts.get(dom, 0) + 1
                day_of_month = max(dom_counts, key=dom_counts.get)

        if n >= 4 and cadence_std is not None and cadence_std <= 5:
            rc = RecurrenceClass.CONFIRMED_RECURRING
        elif n >= 3 and cadence_std is not None and cadence_std <= 10:
            rc = RecurrenceClass.STRONG_RECURRING
        elif n >= 2:
            rc = RecurrenceClass.VARIABLE_PATTERN
        elif n == 1:
            rc = RecurrenceClass.ONE_TIME
        else:
            rc = RecurrenceClass.NONE

        if settled_amounts:
            recent = settled_amounts[-6:]
            typical_amount = _trimmed_median(recent)
            amount_std = float(statistics.stdev([float(a) for a in recent])) if len(recent) >= 2 else None
        else:
            typical_amount = Decimal('0')
            amount_std = None

        most_recent = max(evs, key=lambda e: e.settlement_date or date.min)
        first_ev = evs[0]

        streams.append(RecurringStream(
            key=key,
            category=first_ev.category,
            direction=first_ev.direction,
            recurrence_class=rc,
            cadence_days=cadence_days,
            cadence_std=cadence_std,
            day_of_month=day_of_month,
            typical_amount=typical_amount,
            amount_std=amount_std,
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
    """
    Build RecurringStream objects from aggregated variable category events.

    Strategy: compute average WEEKLY spend for each variable category.
    Project as weekly occurrences.
    """
    streams = []
    for key, evs in groups.items():
        settled = sorted(
            [e for e in evs
             if e.cash_type in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME)
             and e.settlement_date is not None
             and e.settlement_date <= as_of_date],
            key=lambda e: e.settlement_date,
        )

        if not settled:
            continue

        all_dates = [e.settlement_date for e in evs if e.settlement_date]
        last_date = max(all_dates) if all_dates else None
        first_settle = settled[0].settlement_date
        last_settle = settled[-1].settlement_date

        # Total observation window in weeks
        obs_days = (last_settle - first_settle).days
        obs_weeks = max(1, obs_days / 7)
        obs_months = max(1, obs_days / 30.44)

        # Total spend over observation period
        settled_amounts = [e.amount_home for e in settled if e.amount_home > 0]
        total_spend = sum(settled_amounts)

        n = len(settled)

        # Average weekly spend
        weekly_spend = total_spend / Decimal(str(obs_weeks))
        monthly_spend = total_spend / Decimal(str(obs_months))

        # For projection: use WEEKLY cadence with per-occurrence amount = weekly_spend
        # This produces one projected item per week which is cleaner
        cadence_days = 7.0
        typical_amount = weekly_spend

        if n >= 4 and obs_days >= 30:
            rc = RecurrenceClass.CONFIRMED_RECURRING
        elif n >= 2 and obs_days >= 14:
            rc = RecurrenceClass.STRONG_RECURRING
        elif n >= 1:
            rc = RecurrenceClass.VARIABLE_PATTERN
        else:
            rc = RecurrenceClass.NONE

        most_recent = max(evs, key=lambda e: e.settlement_date or date.min)
        first_ev = evs[0]

        streams.append(RecurringStream(
            key=key,
            category=first_ev.category,
            direction=first_ev.direction,
            recurrence_class=rc,
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


def project_next_occurrences(
    stream: RecurringStream,
    from_date: date,
    to_date: date,
) -> List[date]:
    """
    Project future occurrence dates for a recurring stream.
    Only projects for CONFIRMED_RECURRING, STRONG_RECURRING, VARIABLE_PATTERN.
    """
    if stream.recurrence_class in (RecurrenceClass.ONE_TIME, RecurrenceClass.NONE):
        return []
    if stream.last_date is None or stream.cadence_days is None:
        return []

    cadence = round(stream.cadence_days)
    if cadence <= 0:
        return []

    occurrences: List[date] = []

    # Start from last known date + cadence
    next_dt = stream.last_date + timedelta(days=cadence)

    # If monthly with day_of_month anchor, snap to anchor
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


def _next_day_of_month(after: date, day: int, approx_days: int) -> date:
    """Return the next date at day `day` of the next month."""
    import calendar
    year = after.year
    month = after.month + 1
    if month > 12:
        month = 1
        year += 1
    max_day = calendar.monthrange(year, month)[1]
    actual_day = min(day, max_day)
    return date(year, month, actual_day)
