"""
v3/risk_engine/stress_buffers.py

Applies empirical P90 residual uncertainty buffers to variable expense categories.
Derived from out-of-time residual calibration in Phase 2:
- Groceries: +24.0%
- Transport: +24.2%
- Dining: +23.9%
- Utilities: +12.5%
- Shopping: +12.6%
- Entertainment: +12.2%
- Healthcare: +10.7%
- Fixed expenses: +0.0% (rent, debt repayments, subscriptions)
"""
from __future__ import annotations
from decimal import Decimal
import copy
from typing import Dict, Optional

# Add 'code' to path for V2 dataclasses (read-only)
import sys, os
sys.path.insert(0, os.path.abspath('code'))
from financial_state import FinancialState, ScheduledItem


DEFAULT_P90_STRESS_FACTORS: Dict[str, Decimal] = {
    'groceries': Decimal('1.240'),
    'transport': Decimal('1.242'),
    'dining': Decimal('1.239'),
    'utilities': Decimal('1.125'),
    'shopping': Decimal('1.126'),
    'entertainment': Decimal('1.122'),
    'healthcare': Decimal('1.107'),
    'personal_care': Decimal('1.150'),
    'clothing': Decimal('1.150'),
    'miscellaneous': Decimal('1.200'),
    # Fixed categories have zero variance
    'rent': Decimal('1.000'),
    'debt_repayment': Decimal('1.000'),
    'insurance': Decimal('1.000'),
    'housing': Decimal('1.000'),
    'streaming': Decimal('1.000'),
    'music_subscription': Decimal('1.000'),
    'cloud_storage': Decimal('1.000'),
    'delivery_membership': Decimal('1.000'),
    'education': Decimal('1.000'),
    'family_support': Decimal('1.000'),
    'gym': Decimal('1.000'),
}


def build_stressed_state(
    state: FinancialState,
    stress_factors: Optional[Dict[str, Decimal]] = None,
) -> FinancialState:
    """
    Constructs an isolated, P90-stressed FinancialState.
    Scales recurring variable debits by category stress factor.
    Guaranteed: Original state is untouched.
    """
    factors = stress_factors or DEFAULT_P90_STRESS_FACTORS
    stressed = copy.deepcopy(state)

    stressed_debits = []
    for item in stressed.recurring_debits:
        factor = factors.get(item.category, Decimal('1.000'))
        if factor > Decimal('1.000') and item.amount < Decimal('0'):
            stressed_item = ScheduledItem(
                event_id=item.event_id,
                date=item.date,
                amount=item.amount * factor,
                category=item.category,
                description=f"{item.description} [P90 stress]",
                source=item.source,
                flexibility=item.flexibility,
                minimum_allowed_amount=item.minimum_allowed_amount,
                event_id_for_change=item.event_id_for_change,
            )
            stressed_debits.append(stressed_item)
        else:
            stressed_debits.append(item)

    stressed.recurring_debits = stressed_debits
    return stressed
