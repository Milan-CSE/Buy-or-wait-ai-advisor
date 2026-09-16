"""
financial_state.py (v2)
Constructs the complete per-user financial state as of the request_date.

KEY CHANGE: Recurring expense projection uses CATEGORY-LEVEL monthly averages
from the last 3 months of settled history. This avoids the double-counting
problem from multiple sub-streams within a category.

Income projection: ONLY if there are explicitly scheduled future events OR
if a salary stream has 3+ settled occurrences AND the most recent salary
description does NOT indicate termination ("final", "last", "terminated" etc.)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple
import calendar
import statistics

from data_loader import Dataset, FinancialProfile
from currency import FXEngine
from evidence import build_message_evidence_index, MessageEvidence, MessageEvidenceType
from event_lifecycle import (
    LifecycleEvent, CashType, resolve_user_events
)
from recurrence import RecurringStream


FORECAST_HORIZON_DAYS = 90

# Keywords in the most recent salary description that signal no future salary
SALARY_TERMINATION_KEYWORDS = [
    'final', 'last ', 'terminated', 'leaving', 'resignation', 'exit',
    'employment ended', 'last month', 'last payroll', 'final payroll',
]

# Categories that we project as fixed monthly recurring (use exact cadence from history)
FIXED_CATEGORIES = frozenset([
    'rent', 'utilities', 'debt_repayment', 'insurance', 'housing',
    'streaming', 'music_subscription', 'cloud_storage', 'delivery_membership',
    'education', 'family_support', 'gym', 'shopping', 'entertainment', 'healthcare',
])

# Categories where we aggregate weekly/frequent spend from history
VARIABLE_CATEGORIES = frozenset([
    'groceries', 'transport', 'dining',
    'personal_care', 'clothing', 'fitness', 'miscellaneous',
    'travel', 'gifts', 'childcare', 'electronics',
])


@dataclass
class ScheduledItem:
    """A single confirmed future cashflow item."""
    event_id: Optional[str]
    date: date
    amount: Decimal
    category: str
    description: str
    source: str
    flexibility: str = 'fixed'
    minimum_allowed_amount: Optional[Decimal] = None
    event_id_for_change: Optional[str] = None


@dataclass
class FinancialState:
    user_id: str
    request_id: str
    request_date: date
    home_currency: str

    starting_balance: Decimal
    balance_before_pending: Decimal
    minimum_balance: Decimal
    pending_debit_total: Decimal

    protected_categories: List[str]
    reducible_categories: List[str]
    stoppable_categories: List[str]
    payment_methods: List[str]
    max_installment_months: Optional[Decimal]

    lifecycle_events: List[LifecycleEvent]

    future_debits: List[ScheduledItem]
    future_income: List[ScheduledItem]
    recurring_debits: List[ScheduledItem]
    recurring_income: List[ScheduledItem]

    # Kept for compatibility with spending_optimizer
    recurring_streams: List[RecurringStream]
    message_amendments: List[MessageEvidence]


def _is_salary_terminated(events: List[LifecycleEvent], user_messages: Optional[List[MessageEvidence]] = None) -> bool:
    """Check if the most recent salary event or employer message indicates no future salary."""
    if user_messages:
        for ev in user_messages:
            if ev.evidence_type == MessageEvidenceType.CONTRACT_TERMINATED:
                return True

    salary_events = [e for e in events
                     if e.category == 'salary' and e.cash_type in
                     (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME)
                     and e.settlement_date]
    if not salary_events:
        return False
    latest = max(salary_events, key=lambda e: e.settlement_date)
    desc = latest.description.lower()
    return any(kw in desc for kw in SALARY_TERMINATION_KEYWORDS)


def _monthly_category_avg(
    events: List[LifecycleEvent],
    category: str,
    direction: str,
    as_of_date: date,
    lookback_days: int = 90,
) -> Decimal:
    """
    Compute average monthly amount for a category from last `lookback_days` of settled history.
    """
    start = as_of_date - timedelta(days=lookback_days)
    settled = [e for e in events
               if e.category == category
               and e.direction == direction
               and e.cash_type in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME)
               and e.settlement_date
               and start <= e.settlement_date <= as_of_date
               and e.amount_home > 0]
    if not settled:
        return Decimal('0')
    total = sum(e.amount_home for e in settled)
    # Normalize to monthly amount
    monthly = total * Decimal('30') / Decimal(str(lookback_days))
    return monthly


def _project_fixed_category(
    events: List[LifecycleEvent],
    category: str,
    direction: str,
    as_of_date: date,
    horizon_end: date,
) -> List[ScheduledItem]:
    """
    Project a fixed recurring category by finding the typical day-of-month and amount.
    Uses last 6 settled occurrences to determine cadence and amount.
    """
    settled = sorted(
        [e for e in events
         if e.category == category
         and e.direction == direction
         and e.cash_type in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME)
         and e.settlement_date
         and e.settlement_date <= as_of_date
         and e.amount_home > 0],
        key=lambda e: e.settlement_date,
    )
    if not settled:
        return []

    n = len(settled)
    if n < 2:
        # Only one occurrence - can't determine cadence
        # Use a conservative monthly projection based on last event
        last = settled[-1]
        items = []
        next_dt = last.settlement_date + timedelta(days=30)
        while next_dt <= horizon_end:
            if next_dt > as_of_date:
                sign = Decimal('-1') if direction == 'debit' else Decimal('1')
                items.append(ScheduledItem(
                    event_id=None,
                    date=next_dt,
                    amount=sign * last.amount_home,
                    category=category,
                    description=f'[recurring] {category}',
                    source='recurring',
                    flexibility=last.flexibility,
                    minimum_allowed_amount=last.minimum_allowed_amount,
                    event_id_for_change=last.event_id,
                ))
            next_dt = next_dt + timedelta(days=30)
        return items

    # Compute average cadence from recent events
    recent = settled[-6:] if n >= 6 else settled
    intervals = [(recent[i].settlement_date - recent[i-1].settlement_date).days
                 for i in range(1, len(recent))]
    avg_cadence = sum(intervals) / len(intervals)

    # Get typical day of month
    dom_counts: Dict[int, int] = {}
    for e in recent:
        dom = e.settlement_date.day
        dom_counts[dom] = dom_counts.get(dom, 0) + 1
    typical_dom = max(dom_counts, key=dom_counts.get)

    # Get typical amount (trimmed median of recent)
    amounts = sorted([e.amount_home for e in recent])
    mid_idx = len(amounts) // 2
    if len(amounts) % 2 == 1:
        typical_amount = amounts[mid_idx]
    else:
        typical_amount = (amounts[mid_idx-1] + amounts[mid_idx]) / 2

    most_recent_ev = recent[-1]
    flexibility = most_recent_ev.flexibility
    min_allowed = most_recent_ev.minimum_allowed_amount
    ref_event_id = most_recent_ev.event_id

    items = []
    last_date = settled[-1].settlement_date

    # Project from last date
    if 25 <= avg_cadence <= 35:
        # Monthly: step by months using day_of_month
        current_yr = last_date.year
        current_mo = last_date.month
        while True:
            # Advance to next month
            current_mo += 1
            if current_mo > 12:
                current_mo = 1
                current_yr += 1

            max_day = calendar.monthrange(current_yr, current_mo)[1]
            proj_day = min(typical_dom, max_day)
            proj_date = date(current_yr, current_mo, proj_day)
            if proj_date > horizon_end:
                break
            if proj_date >= as_of_date:
                sign = Decimal('-1') if direction == 'debit' else Decimal('1')
                items.append(ScheduledItem(
                    event_id=None,
                    date=proj_date,
                    amount=sign * typical_amount,
                    category=category,
                    description=f'[recurring] {category}',
                    source='recurring',
                    flexibility=flexibility,
                    minimum_allowed_amount=min_allowed,
                    event_id_for_change=ref_event_id,
                ))
    else:
        # Non-monthly cadence: step by avg_cadence days
        next_dt = last_date + timedelta(days=round(avg_cadence))
        while next_dt <= horizon_end:
            if next_dt > as_of_date:
                sign = Decimal('-1') if direction == 'debit' else Decimal('1')
                items.append(ScheduledItem(
                    event_id=None,
                    date=next_dt,
                    amount=sign * typical_amount,
                    category=category,
                    description=f'[recurring] {category}',
                    source='recurring',
                    flexibility=flexibility,
                    minimum_allowed_amount=min_allowed,
                    event_id_for_change=ref_event_id,
                ))
            next_dt = next_dt + timedelta(days=round(avg_cadence))

    return items


def _project_variable_category(
    events: List[LifecycleEvent],
    category: str,
    direction: str,
    as_of_date: date,
    horizon_end: date,
    use_daily_burn: bool = True,
) -> List[ScheduledItem]:
    """
    Project variable spending categories (groceries, transport, dining).
    If use_daily_burn is True (default), spreads expenditure evenly as a daily burn rate.
    If False, uses legacy discrete stepping by observed cadence.
    """
    settled = sorted(
        [e for e in events
         if e.category == category and e.direction == direction
         and e.cash_type in (CashType.IMMEDIATE_DEBIT, CashType.SETTLED_INCOME)
         and e.settlement_date and e.settlement_date <= as_of_date
         and e.amount_home > 0],
        key=lambda e: e.settlement_date,
    )
    if not settled:
        return []

    n = len(settled)
    most_recent_ev = settled[-1]
    flexibility = most_recent_ev.flexibility
    min_allowed = most_recent_ev.minimum_allowed_amount
    ref_event_id = most_recent_ev.event_id

    # Compute cadence
    if n >= 2:
        recent = settled[-8:] if n >= 8 else settled
        intervals = [(recent[i].settlement_date - recent[i-1].settlement_date).days
                     for i in range(1, len(recent))]
        avg_cadence = sum(intervals) / len(intervals)
        if avg_cadence <= 0:
            avg_cadence = 7.0
    else:
        avg_cadence = 7.0

    cadence_days = max(3, round(avg_cadence))

    # Compute typical amount per occurrence (trimmed median of recent settled)
    recent_amts = [e.amount_home for e in (settled[-8:] if n >= 8 else settled)]
    sorted_amts = sorted(recent_amts)
    mid_idx = len(sorted_amts) // 2
    if len(sorted_amts) % 2 == 1:
        typical_amount = sorted_amts[mid_idx]
    else:
        typical_amount = (sorted_amts[mid_idx-1] + sorted_amts[mid_idx]) / 2

    items = []
    sign = Decimal('-1') if direction == 'debit' else Decimal('1')

    if use_daily_burn:
        # Step 1: count projected occurrences under observed cadence to get total 90-day spend
        occ_count = 0
        last_date = settled[-1].settlement_date
        next_dt = last_date + timedelta(days=cadence_days)
        while next_dt <= horizon_end:
            if next_dt >= as_of_date:
                occ_count += 1
            next_dt += timedelta(days=cadence_days)
        if occ_count == 0:
            occ_count = max(1, round(90 / cadence_days))

        total_burn = typical_amount * Decimal(occ_count)
        days = (horizon_end - as_of_date).days + 1
        daily_amt = total_burn / Decimal(days)
        daily_min_allowed = (min_allowed * Decimal(occ_count) / Decimal(days)) if min_allowed else None

        curr = as_of_date
        while curr <= horizon_end:
            items.append(ScheduledItem(
                event_id=None,
                date=curr,
                amount=sign * daily_amt,
                category=category,
                description=f'[daily burn] {category}',
                source='recurring',
                flexibility=flexibility,
                minimum_allowed_amount=daily_min_allowed,
                event_id_for_change=ref_event_id,
            ))
            curr += timedelta(days=1)
    else:
        last_date = settled[-1].settlement_date
        next_dt = last_date + timedelta(days=cadence_days)
        while next_dt <= horizon_end:
            if next_dt >= as_of_date:
                items.append(ScheduledItem(
                    event_id=None,
                    date=next_dt,
                    amount=sign * typical_amount,
                    category=category,
                    description=f'[recurring] {category}',
                    source='recurring',
                    flexibility=flexibility,
                    minimum_allowed_amount=min_allowed,
                    event_id_for_change=ref_event_id,
                ))
            next_dt += timedelta(days=cadence_days)

    return items


def is_salary_reliable_for_forecast(
    events: List[LifecycleEvent],
    user_messages: Optional[List[MessageEvidence]] = None,
    is_monthly: bool = False,
    has_scheduled: bool = False,
) -> bool:
    """
    General income reliability classifier:
    Determines whether a user's income stream is sufficiently confirmed/reliable
    to be projected as recurring future income in the conservative 90-day safety forecast.

    Rules:
    1. Confirmed scheduled income: If an explicit confirmed scheduled income event exists,
       it is considered reliable.
    2. Service provider unwithdrawable/pending warning: If an untrusted service provider message
       states that payouts are pending, subject to change, or unwithdrawable, the platform
       earnings cannot be treated as guaranteed cashflow.
    3. Variable gig/freelance platform payouts: Freelance and gig platform earnings
       (e.g., delivery, ride-hailing, task marketplace payouts, app earnings) are variable
       and non-contractual; they must not be projected as guaranteed recurring salary unless
       formally scheduled.
    4. Cadence stability: Contractual employer payroll operates on a regular monthly cadence
       (or consistent day of the month). Irregular or non-monthly cadence streams without
       explicit scheduling are not assumed to recur.
    5. Established employer payroll: Standard regular payroll with stable monthly cadence
       is projected.
    """
    if has_scheduled:
        return True

    if user_messages:
        for ev in user_messages:
            if ev.source_type == 'service_provider':
                txt = (ev.raw_note or '').lower()
                if any(w in txt for w in [
                    'pending', 'withdrawable', 'tertunda', 'ditarik',
                    'can change', 'dapat berubah', 'not withdrawable',
                ]):
                    return False

    salary_events = [
        e for e in events
        if e.category == 'salary'
        and e.cash_type in (CashType.SETTLED_INCOME, CashType.CONFIRMED_INCOME)
    ]
    if not salary_events:
        return False

    descs = [(e.description or '').lower() for e in salary_events]
    gig_keywords = [
        'payout', 'app earnings', 'marketplace payout', 'driver platform',
        'delivery platform', 'task marketplace',
    ]
    is_gig = any(any(k in d for k in gig_keywords) for d in descs)
    if is_gig:
        return False

    if not is_monthly:
        return False

    return True


def _project_salary(
    events: List[LifecycleEvent],
    as_of_date: date,
    horizon_end: date,
    scheduled_income_dates: Set[date],
    user_messages: Optional[List[MessageEvidence]] = None,
    filter_unreliable_income: bool = True,
) -> List[ScheduledItem]:
    """
    Project salary/income recurring only if:
    1. The most recent salary description or employer message does NOT indicate termination
    2. Income stream is verified reliable (not variable gig/platform or pending unwithdrawable payouts)
    3. There are enough events to determine cadence:
       - At least 2 settled, OR
       - At least 1 settled + 1 confirmed scheduled (for new employees)

    Returns projected salary items beyond what's already scheduled.
    """
    if _is_salary_terminated(events, user_messages):
        return []  # Don't project if salary is terminated

    # All salary events (settled + confirmed_income scheduled), excluding unconfirmed variable commission/bonus and one-time arrears
    salary_all = sorted(
        [e for e in events
         if e.category == 'salary'
         and e.cash_type in (CashType.CONFIRMED_INCOME, CashType.SETTLED_INCOME)
         and e.settlement_date
         and e.amount_home > 0
         and not any(w in (e.description or '').lower() for w in ['commission', 'bonus', 'komisi', 'arrears', 'one-time', 'adjustment'])],
        key=lambda e: e.settlement_date,
    )

    salary_settled = [e for e in salary_all if e.cash_type == CashType.SETTLED_INCOME
                      and e.settlement_date <= as_of_date]
    salary_scheduled = [e for e in salary_all if e.cash_type == CashType.CONFIRMED_INCOME]

    # Need at least 2 total events to determine cadence
    if len(salary_all) < 2:
        return []

    # Compute cadence from last 6 events across settled+scheduled
    recent = salary_all[-6:]
    intervals = [(recent[i].settlement_date - recent[i-1].settlement_date).days
                 for i in range(1, len(recent))]
    avg_cadence = sum(intervals) / len(intervals)
    if avg_cadence <= 0:
        return []

    # Typical amount: use scheduled salary amount if available (most reliable),
    # else use median of settled amounts
    if salary_scheduled:
        # Use the amount from the most recent scheduled salary
        typical_amount = max(salary_scheduled, key=lambda e: e.settlement_date).amount_home
    else:
        amounts = sorted([e.amount_home for e in recent])
        mid_idx = len(amounts) // 2
        if len(amounts) % 2 == 1:
            typical_amount = amounts[mid_idx]
        else:
            typical_amount = (amounts[mid_idx-1] + amounts[mid_idx]) / 2

    # Project from the last known salary date (settled or scheduled)
    last_date = salary_all[-1].settlement_date

    # Typical day of month:
    # First check if any employer message specifies an effective date
    msg_dom = None
    if user_messages:
        for ev in user_messages:
            if ev.effective_date and ev.evidence_type in (
                MessageEvidenceType.SALARY_CONFIRMED,
                MessageEvidenceType.SALARY_DATE,
                MessageEvidenceType.SALARY_AMENDMENT,
            ):
                msg_dom = ev.effective_date.day
                break

    # Count DOMs from history
    dom_counts: Dict[int, int] = {}
    for e in recent:
        dom = e.settlement_date.day
        dom_counts[dom] = dom_counts.get(dom, 0) + 1
    most_common_dom, dom_freq = max(dom_counts.items(), key=lambda x: x[1])

    # If all or majority share the same DOM, or cadence is ~monthly, treat as monthly
    is_monthly = (25 <= avg_cadence <= 35) or (dom_freq >= 2 and dom_freq / len(recent) >= 0.5)

    has_scheduled = bool(salary_scheduled)

    # General income reliability check
    if filter_unreliable_income and not is_salary_reliable_for_forecast(
        events, user_messages, is_monthly=is_monthly, has_scheduled=has_scheduled
    ):
        return []

    typical_dom = msg_dom if msg_dom is not None else (most_common_dom if is_monthly else None)

    items = []
    if typical_dom and is_monthly:
        current_yr = last_date.year
        current_mo = last_date.month
        while True:
            current_mo += 1
            if current_mo > 12:
                current_mo = 1
                current_yr += 1
            max_day = calendar.monthrange(current_yr, current_mo)[1]
            proj_day = min(typical_dom, max_day)
            proj_date = date(current_yr, current_mo, proj_day)
            if proj_date > horizon_end:
                break
            if proj_date >= as_of_date and proj_date not in scheduled_income_dates:
                items.append(ScheduledItem(
                    event_id=None,
                    date=proj_date,
                    amount=typical_amount,
                    category='salary',
                    description='[recurring] salary',
                    source='recurring',
                ))
    else:
        next_dt = last_date + timedelta(days=round(avg_cadence))
        while next_dt <= horizon_end:
            if next_dt > as_of_date and next_dt not in scheduled_income_dates:
                items.append(ScheduledItem(
                    event_id=None,
                    date=next_dt,
                    amount=typical_amount,
                    category='salary',
                    description='[recurring] salary',
                    source='recurring',
                ))
            next_dt = next_dt + timedelta(days=round(avg_cadence))

    return items



def build_financial_state(
    user_id: str,
    request_id: str,
    request_date: date,
    dataset: Dataset,
    fx: FXEngine,
    use_daily_burn: bool = True,
    filter_unreliable_income: bool = True,
) -> FinancialState:
    """Build complete financial state for a user as of request_date."""
    profile: FinancialProfile = dataset.profiles[user_id]
    horizon_end = request_date + timedelta(days=FORECAST_HORIZON_DAYS)

    # Step 1: Resolve lifecycle events
    lifecycle_events = resolve_user_events(user_id, dataset, fx)

    # Step 2: Compute starting balance (subtract pending debits)
    pending_debit_total = Decimal('0')
    for ev in lifecycle_events:
        if ev.cash_type == CashType.IMMEDIATE_DEBIT and ev.original_status == 'pending':
            pending_debit_total += ev.amount_home
    starting_balance = profile.current_available_balance - pending_debit_total

    # Step 3: Gather scheduled future items (explicit events only)
    future_debits: List[ScheduledItem] = []
    future_income: List[ScheduledItem] = []

    for ev in lifecycle_events:
        settle_dt = ev.settlement_date
        if settle_dt is None or settle_dt <= request_date or settle_dt > horizon_end:
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

    # Step 4: Project recurring expenses
    recurring_debits: List[ScheduledItem] = []
    recurring_income: List[ScheduledItem] = []

    # Track scheduled categories to avoid double-counting
    scheduled_debit_cats: Set[str] = set(item.category for item in future_debits)
    scheduled_income_dates: Set[date] = set(item.date for item in future_income if item.category == 'salary')

    # Project FIXED recurring expense categories
    for cat in FIXED_CATEGORIES:
        # Skip if explicitly scheduled (already counted)
        scheduled_dates_for_cat = set(item.date for item in future_debits if item.category == cat)
        projected = _project_fixed_category(
            lifecycle_events, cat, 'debit', request_date, horizon_end
        )
        # Remove dates already covered by scheduled items
        for item in projected:
            if item.date not in scheduled_dates_for_cat:
                recurring_debits.append(item)

    # Project VARIABLE recurring expense categories
    for cat in VARIABLE_CATEGORIES:
        projected = _project_variable_category(
            lifecycle_events, cat, 'debit', request_date, horizon_end, use_daily_burn=use_daily_burn
        )
        recurring_debits.extend(projected)

    # Step 5: Message amendments lookup
    msg_evidence_index = build_message_evidence_index(dataset)
    user_messages = msg_evidence_index.get(user_id, [])

    # Project salary/income (only if not terminated and reliable)
    salary_items = _project_salary(
        lifecycle_events, request_date, horizon_end, scheduled_income_dates, user_messages,
        filter_unreliable_income=filter_unreliable_income,
    )
    recurring_income.extend(salary_items)

    # Apply message amendments
    _apply_salary_amendments(user_messages, future_income, recurring_income)
    _apply_rent_amendments(user_messages, future_debits, recurring_debits, profile)

    # Step 6: Build recurring streams (for spending optimizer compatibility)
    from recurrence import infer_recurring_streams
    recurring_streams = infer_recurring_streams(lifecycle_events, as_of_date=request_date)

    return FinancialState(
        user_id=user_id,
        request_id=request_id,
        request_date=request_date,
        home_currency=profile.home_currency,
        starting_balance=starting_balance,
        balance_before_pending=profile.current_available_balance,
        minimum_balance=profile.minimum_balance_to_keep,
        pending_debit_total=pending_debit_total,
        protected_categories=profile.expense_categories_to_protect,
        reducible_categories=profile.expense_categories_user_is_willing_to_reduce,
        stoppable_categories=profile.expense_categories_user_is_willing_to_stop,
        payment_methods=profile.payment_methods_user_will_consider,
        max_installment_months=profile.max_installment_months,
        lifecycle_events=lifecycle_events,
        future_debits=future_debits,
        future_income=future_income,
        recurring_debits=recurring_debits,
        recurring_income=recurring_income,
        recurring_streams=recurring_streams,
        message_amendments=user_messages,
    )


def _apply_salary_amendments(
    amendments: List[MessageEvidence],
    future_income: List[ScheduledItem],
    recurring_income: List[ScheduledItem],
) -> None:
    for ev in amendments:
        if ev.evidence_type not in (MessageEvidenceType.SALARY_AMENDMENT,
                                    MessageEvidenceType.SALARY_CONFIRMED):
            continue
        if ev.amount is None:
            continue
        for item in future_income + recurring_income:
            if item.category == 'salary':
                item.amount = ev.amount


def _apply_rent_amendments(
    amendments: List[MessageEvidence],
    future_debits: List[ScheduledItem],
    recurring_debits: List[ScheduledItem],
    profile: FinancialProfile,
) -> None:
    for ev in amendments:
        if ev.evidence_type != MessageEvidenceType.RENT_AMENDMENT:
            continue
        for item in future_debits + recurring_debits:
            if item.category != 'rent':
                continue
            if ev.amount is not None:
                item.amount = -ev.amount
            elif ev.percentage_change is not None:
                factor = (Decimal('1') + ev.percentage_change / 100)
                item.amount = item.amount * factor
