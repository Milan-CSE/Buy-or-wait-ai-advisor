"""
buyorwait_engine/decision/spending.py

Enumerates all legal combinations of up to 3 discretionary spending changes
(stop or reduce_to) on non-protected, flexible categories.
Enforces that reduced amounts map to the catalog minimum_allowed_amount.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Dict, List, Optional, Set

from buyorwait_engine.domain.state import FinancialState, ScheduledItem


@dataclass
class SpendingChangeOption:
    event_id: str
    change_type: str      # 'stop' | 'reduce'
    new_amount: Optional[Decimal]    # None for stop; Decimal for reduce_to
    category: str
    savings_per_occurrence: Decimal
    num_occurrences: int


def get_eligible_changes(state: FinancialState) -> List[SpendingChangeOption]:
    """
    Return all eligible single spending changes for a user.
    """
    protected = set(state.protected_categories)
    stoppable_cats = set(state.stoppable_categories)
    reducible_cats = set(state.reducible_categories)

    seen_event_ids: Set[str] = set()
    options: List[SpendingChangeOption] = []

    orig_min_amts = {
        ev.event_id: ev.minimum_allowed_amount
        for ev in getattr(state, 'lifecycle_events', [])
        if ev.minimum_allowed_amount is not None
    }

    all_debit_items: List[ScheduledItem] = state.future_debits + state.recurring_debits

    for item in all_debit_items:
        cat = item.category
        if cat in protected:
            continue
        if item.event_id_for_change is None:
            continue
        event_id = item.event_id_for_change
        if event_id in seen_event_ids:
            continue

        occurrences = sum(
            1 for i in all_debit_items
            if i.event_id_for_change == event_id
        )

        amount_per_occ = abs(item.amount)
        flexibility = item.flexibility

        # Can stop?
        if (flexibility in ('stoppable', 'reducible_or_stoppable')) and (cat in stoppable_cats):
            options.append(SpendingChangeOption(
                event_id=event_id,
                change_type='stop',
                new_amount=None,
                category=cat,
                savings_per_occurrence=amount_per_occ,
                num_occurrences=occurrences,
            ))
            seen_event_ids.add(event_id)

        # Can reduce?
        elif (flexibility in ('reducible', 'reducible_or_stoppable')) and (cat in reducible_cats):
            target_min = orig_min_amts.get(event_id, item.minimum_allowed_amount) or Decimal('0')
            scaled_min = item.minimum_allowed_amount or Decimal('0')
            savings = amount_per_occ - scaled_min
            if savings > 0 or amount_per_occ > target_min:
                options.append(SpendingChangeOption(
                    event_id=event_id,
                    change_type='reduce',
                    new_amount=target_min,
                    category=cat,
                    savings_per_occurrence=savings,
                    num_occurrences=occurrences,
                ))
                seen_event_ids.add(event_id)

    return options


def enumerate_spending_change_combos(
    state: FinancialState,
    max_actions: int = 3,
) -> List[Dict[str, Optional[Decimal]]]:
    """
    Enumerate all legal combinations of up to `max_actions` spending changes.
    Returns a list of spending_change dicts:
      {event_id: None (stop) | Decimal (reduce_to new_amount)}
    Always includes the empty dict (no changes).
    """
    options = get_eligible_changes(state)
    results: List[Dict[str, Optional[Decimal]]] = [{}]

    for r in range(1, min(max_actions, len(options)) + 1):
        for combo in combinations(options, r):
            change: Dict[str, Optional[Decimal]] = {}
            for opt in combo:
                change[opt.event_id] = opt.new_amount
            results.append(change)

    return results


def format_spending_changes(
    changes: Dict[str, Optional[Decimal]],
    lifecycle_events_by_id: Optional[Dict] = None,
) -> str:
    """
    Format spending changes as 'stop:event_id|reduce_to:event_id:amount' or 'none'.
    """
    if not changes:
        return 'none'
    parts = []
    for event_id, new_amount in sorted(changes.items()):
        if new_amount is None:
            parts.append(f'stop:{event_id}')
        else:
            s = f'{new_amount:.2f}'
            if s.endswith('.00'):
                s = s[:-3]
            parts.append(f'reduce_to:{event_id}:{s}')
    return '|'.join(parts)
