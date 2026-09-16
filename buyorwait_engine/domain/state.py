"""
buyorwait_engine/domain/state.py

Defines the core in-memory state objects:
- ScheduledItem: Individual confirmed cashflow event (debit or credit).
- LifecycleEvent: Resolved historical or upcoming event with cashflow classification.
- FinancialState: Complete 90-day reconstructed personal balance sheet.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, List, Optional

from buyorwait_engine.domain.enums import CashType


FORECAST_HORIZON_DAYS = 90

SALARY_TERMINATION_KEYWORDS = [
    'final', 'last ', 'terminated', 'leaving', 'resignation', 'exit',
    'employment ended', 'last month', 'last payroll', 'final payroll',
]

FIXED_CATEGORIES = frozenset([
    'rent', 'utilities', 'debt_repayment', 'insurance', 'housing',
    'streaming', 'music_subscription', 'cloud_storage', 'delivery_membership',
    'education', 'family_support', 'gym', 'shopping', 'entertainment', 'healthcare',
])

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
class LifecycleEvent:
    """An event resolved with respect to its cash state, linked events, and currency."""
    event_id: str
    user_id: str
    category: str
    description: str
    event_type: str
    direction: str
    original_status: str
    settlement_date: Optional[date]
    event_date: Optional[date]
    amount_home: Decimal
    original_currency: str
    cash_type: CashType
    flexibility: str = 'fixed'
    minimum_allowed_amount: Optional[Decimal] = None
    linked_event_id: Optional[str] = None


@dataclass
class FinancialState:
    """
    Complete consolidated personal balance sheet for a user as of a request date.
    All monetary amounts are Decimal.
    """
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

    lifecycle_events: List[LifecycleEvent] = field(default_factory=list)

    future_debits: List[ScheduledItem] = field(default_factory=list)
    future_income: List[ScheduledItem] = field(default_factory=list)
    recurring_debits: List[ScheduledItem] = field(default_factory=list)
    recurring_income: List[ScheduledItem] = field(default_factory=list)

    recurring_streams: List[Any] = field(default_factory=list)
    message_amendments: List[Any] = field(default_factory=list)
