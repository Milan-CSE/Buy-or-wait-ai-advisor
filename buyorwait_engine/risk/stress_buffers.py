"""
buyorwait_engine/risk/stress_buffers.py

Applies empirical P90 residual uncertainty buffers to variable expense categories.
Guarantees immutability of the base FinancialState.
"""
from __future__ import annotations
import copy
from decimal import Decimal
from typing import Dict, Optional

from buyorwait_engine.domain.state import FinancialState, ScheduledItem
from buyorwait_engine.risk.config import DEFAULT_P90_STRESS_FACTORS, RiskCalibrationConfig


def build_stressed_state(
    state: FinancialState,
    config: Optional[RiskCalibrationConfig] = None,
) -> FinancialState:
    """
    Constructs an isolated, P90-stressed FinancialState.
    Scales recurring variable debits by category stress factor.
    Guaranteed: Original state is untouched.
    """
    factors = config.stress_factors if config else DEFAULT_P90_STRESS_FACTORS
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
