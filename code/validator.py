"""
validator.py
Strict output contract enforcement.
Validates all Decision fields against the spec before writing to output.csv.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from ranker import Decision


VALID_AFFORDABILITY = frozenset([
    'affordable_now', 'affordable_with_plan', 'affordable_later', 'not_affordable'
])

VALID_METHODS = frozenset([
    'full_payment', 'partial_payment', 'installments', 'wait', 'not_recommended'
])


@dataclass
class ValidationError:
    field: str
    message: str


def validate_decision(d: Decision, requested_amount: Decimal) -> List[ValidationError]:
    """
    Validate a Decision against the output contract.
    Returns a list of validation errors (empty = valid).
    """
    errors: List[ValidationError] = []

    # amount_safe_to_pay in [0, requested_amount]
    if d.amount_safe_to_pay < Decimal('0'):
        errors.append(ValidationError('amount_safe_to_pay', f'Negative value: {d.amount_safe_to_pay}'))
    if d.amount_safe_to_pay > requested_amount:
        errors.append(ValidationError('amount_safe_to_pay',
                      f'{d.amount_safe_to_pay} > requested_amount {requested_amount}'))

    # affordability_status valid value
    if d.affordability_status not in VALID_AFFORDABILITY:
        errors.append(ValidationError('affordability_status',
                      f'Invalid value: {d.affordability_status!r}'))

    # recommended_payment_method valid value
    if d.recommended_payment_method not in VALID_METHODS:
        errors.append(ValidationError('recommended_payment_method',
                      f'Invalid value: {d.recommended_payment_method!r}'))

    # affordable_now => earliest_date_for_full_payment is set
    if d.affordability_status == 'affordable_now' and d.earliest_date_for_full_payment is None:
        errors.append(ValidationError('earliest_date_for_full_payment',
                      'Must be set when affordability_status == affordable_now'))

    # not_affordable => earliest_date may be empty
    # (no hard rule violated here)

    # payment_plan format check
    if d.payment_plan not in ('', 'none'):
        for part in d.payment_plan.split('|'):
            if ':' not in part:
                errors.append(ValidationError('payment_plan', f'Invalid part: {part!r}'))
                continue
            dt_str, amt_str = part.split(':', 1)
            try:
                date.fromisoformat(dt_str)
            except ValueError:
                errors.append(ValidationError('payment_plan', f'Invalid date: {dt_str!r}'))
            try:
                Decimal(amt_str)
            except Exception:
                errors.append(ValidationError('payment_plan', f'Invalid amount: {amt_str!r}'))

    # spending_changes_needed format
    if d.spending_changes_needed not in ('', 'none'):
        parts = d.spending_changes_needed.split('|')
        if len(parts) > 3:
            errors.append(ValidationError('spending_changes_needed',
                          f'More than 3 actions: {len(parts)}'))
        for part in parts:
            if part.startswith('stop:'):
                pass  # valid
            elif part.startswith('reduce_to:'):
                sub = part[len('reduce_to:'):]
                if ':' not in sub:
                    errors.append(ValidationError('spending_changes_needed',
                                  f'reduce_to missing amount: {part!r}'))
            else:
                errors.append(ValidationError('spending_changes_needed',
                              f'Unknown action: {part!r}'))

    # decision_explanation non-empty
    if not d.decision_explanation:
        errors.append(ValidationError('decision_explanation', 'Empty explanation'))

    return errors


def coerce_decision(d: Decision, requested_amount: Decimal) -> Decision:
    """
    Attempt to fix minor violations automatically before writing.
    """
    # Clamp safe_amount
    safe = max(Decimal('0'), min(requested_amount, d.amount_safe_to_pay))
    if safe != d.amount_safe_to_pay:
        d = Decision(
            request_id=d.request_id,
            amount_safe_to_pay=safe,
            affordability_status=d.affordability_status,
            recommended_payment_method=d.recommended_payment_method,
            payment_plan=d.payment_plan,
            earliest_date_for_full_payment=d.earliest_date_for_full_payment,
            spending_changes_needed=d.spending_changes_needed,
            decision_explanation=d.decision_explanation,
            best_candidate=d.best_candidate,
        )
    return d
