"""
buyorwait_engine/decision/ranker.py

Selects the best candidate plan using the exact 6-tier lexicographic ranking:
  Tier 1: completes_by_deadline (True preferred)
  Tier 2: avoids_spending_changes (no spending changes preferred)
  Tier 3: minimize_total_cost (lower total_payable)
  Tier 4: start_earlier (earlier first_payment_date)
  Tier 5: fewer_payments (less num_payments)
  Tier 6: feasibility (is_feasible must be True)

Only feasible candidates are ranked.
The fallback to not_recommended is only used if no feasible plan exists.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from buyorwait_engine.domain.state import FinancialState
from buyorwait_engine.decision.candidates import Candidate
from buyorwait_engine.decision.spending import format_spending_changes
from buyorwait_engine.decision.safe_amount import compute_safe_amount
from buyorwait_engine.decision.earliest_date import find_earliest_full_payment_date


VALID_AFFORDABILITY = frozenset([
    'affordable_now', 'affordable_with_plan', 'affordable_later', 'not_affordable'
])
VALID_METHODS = frozenset([
    'full_payment', 'partial_payment', 'installments', 'wait', 'not_recommended'
])


@dataclass
class Decision:
    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str          # "none" or "YYYY-MM-DD:amount|..."
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str   # "none" or "stop:X|reduce_to:Y:Z"
    decision_explanation: str
    best_candidate: Optional[Candidate]


def _rank_key(c: Candidate) -> tuple:
    """Lower = better. Tuples compared lexicographically."""
    return (
        0 if c.completes_by_deadline else 1,
        0 if not c.spending_changes else 1,
        float(c.total_payable),
        float((c.first_payment_date - date(2000, 1, 1)).days) if c.first_payment_date else 99999,
        c.num_payments,
    )


def select_best_candidate(candidates: List[Candidate]) -> Optional[Candidate]:
    """
    Select the best feasible candidate using 6-tier ranking.
    Excludes not_recommended unless it's the only option.
    """
    feasible = [c for c in candidates if c.is_feasible and c.method != 'not_recommended']

    if not feasible:
        fallback = next((c for c in candidates if c.method == 'not_recommended'), None)
        return fallback

    feasible.sort(key=_rank_key)
    return feasible[0]


def _format_payment_plan(candidate: Candidate, requested_amount: Decimal) -> str:
    """Format payment plan as 'YYYY-MM-DD:amount|...' or 'none'."""
    if not candidate.payment_plan:
        return 'none'

    sorted_dates = sorted(candidate.payment_plan.keys())
    parts = []
    for dt in sorted_dates:
        amt = candidate.payment_plan[dt]
        if amt == amt.to_integral():
            fmt_amt = str(int(amt))
        else:
            fmt_amt = f'{amt:.2f}'
        parts.append(f'{dt.isoformat()}:{fmt_amt}')
    return '|'.join(parts)


def _derive_affordability_clean(
    best: Candidate,
    safe_amount: Decimal,
    requested_amount: Decimal,
    earliest_full_date: Optional[date],
    request_date: date,
    completion_date: date,
    payment_methods: List[str],
) -> str:
    """Clean affordability derivation logic."""
    m = best.method

    if m == 'not_recommended':
        return 'not_affordable'

    if m == 'wait':
        return 'affordable_later'

    if m == 'full_payment':
        if not best.spending_changes:
            if best.first_payment_date == request_date:
                return 'affordable_now'
            else:
                return 'affordable_later'
        else:
            return 'affordable_with_plan'

    if m in ('installments', 'partial_payment'):
        return 'affordable_with_plan'

    return 'not_affordable'


def _build_explanation(
    best: Candidate,
    state: FinancialState,
    safe_amount: Decimal,
    requested_amount: Decimal,
    earliest_full_date: Optional[date],
    affordability: str,
) -> str:
    """Build a concise, grounded decision explanation."""
    m = best.method
    bal = state.starting_balance
    minb = state.minimum_balance
    headroom = bal - minb

    parts = []

    if m == 'not_recommended':
        parts.append(
            f'Current balance ({bal:.2f}) is insufficient to cover '
            f'{requested_amount:.2f} while maintaining minimum balance ({minb:.2f}). '
            f'No safe payment plan found within the 90-day forecast window.'
        )
    elif m == 'full_payment':
        if best.spending_changes:
            changes_str = format_spending_changes(best.spending_changes)
            parts.append(
                f'Full payment of {requested_amount:.2f} is affordable today '
                f'after spending adjustments ({changes_str}). '
                f'Balance headroom: {headroom:.2f}, minimum required: {minb:.2f}.'
            )
        else:
            parts.append(
                f'Full payment of {requested_amount:.2f} is affordable on {best.first_payment_date}. '
                f'Starting balance: {bal:.2f}, minimum required: {minb:.2f}.'
            )
    elif m == 'installments':
        parts.append(
            f'Installment plan (option {best.payment_option_id}): '
            f'{best.num_payments} payments of {best.total_payable / best.num_payments:.2f} '
            f'starting {best.first_payment_date}. Total payable: {best.total_payable:.2f}. '
            f'Each payment verified safe against 90-day cashflow forecast.'
        )
    elif m == 'partial_payment':
        parts.append(
            f'Partial payment recommended. '
            f'Pay {safe_amount:.2f} today; remaining {requested_amount - safe_amount:.2f} '
            f'on {best.last_payment_date}. '
            f'Balance headroom today: {headroom:.2f}, minimum: {minb:.2f}.'
        )
    elif m == 'wait':
        parts.append(
            f'Full payment of {requested_amount:.2f} not affordable today '
            f'(safe amount: {safe_amount:.2f}). '
            f'Earliest safe date for full payment: {earliest_full_date}. '
            f'Wait until {best.first_payment_date}.'
        )

    return ' '.join(parts) if parts else 'No suitable explanation available.'


def make_decision(
    request_id: str,
    state: FinancialState,
    all_candidates: List[Candidate],
    requested_amount: Decimal,
    request_date: date,
    completion_date: date,
    safe_amount_no_changes: Decimal,
    earliest_full_date: Optional[date],
) -> Decision:
    """Select the best candidate and produce the full Decision output."""
    best = select_best_candidate(all_candidates)

    if best is None:
        best = Candidate(
            method='not_recommended',
            payment_option_id=None,
            payment_plan={},
            spending_changes={},
            total_payable=Decimal('0'),
            num_payments=0,
            first_payment_date=None,
            last_payment_date=None,
            completes_by_deadline=False,
            is_feasible=True,
            feasibility_note='No candidates generated',
        )

    safe_amount = safe_amount_no_changes
    if best.spending_changes:
        eff_earliest = find_earliest_full_payment_date(state, requested_amount, best.spending_changes)
    else:
        eff_earliest = earliest_full_date

    safe_amount = max(Decimal('0'), min(requested_amount, safe_amount))

    affordability = _derive_affordability_clean(
        best, safe_amount, requested_amount,
        eff_earliest, request_date, completion_date,
        state.payment_methods,
    )

    if affordability == 'affordable_now':
        edfp = request_date
    else:
        edfp = earliest_full_date or eff_earliest

    payment_plan_str = _format_payment_plan(best, requested_amount)

    if best.method in ('wait', 'not_recommended'):
        spending_changes_str = 'none'
    else:
        spending_changes_str = format_spending_changes(best.spending_changes)

    explanation = _build_explanation(
        best, state, safe_amount, requested_amount, eff_earliest, affordability
    )

    return Decision(
        request_id=request_id,
        amount_safe_to_pay=safe_amount,
        affordability_status=affordability,
        recommended_payment_method=best.method,
        payment_plan=payment_plan_str,
        earliest_date_for_full_payment=edfp,
        spending_changes_needed=spending_changes_str,
        decision_explanation=explanation,
        best_candidate=best,
    )
