"""
diagnostics.py
Per-request diagnostic trace for debugging and audit.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from financial_state import FinancialState
from ranker import Decision
from candidates import Candidate


@dataclass
class RequestDiagnostic:
    request_id: str
    user_id: str
    request_date: date
    requested_amount: Decimal
    home_currency: str

    # Financial state summary
    balance_before_pending: Decimal
    pending_debit_total: Decimal
    starting_balance: Decimal
    minimum_balance: Decimal
    headroom: Decimal

    # Cashflow summary
    future_debit_count: int
    future_income_count: int
    recurring_debit_count: int
    recurring_income_count: int

    # Computed values
    safe_amount_no_changes: Decimal
    earliest_full_date: Optional[date]

    # Candidates summary
    num_candidates: int
    candidate_summaries: List[str]

    # Final decision
    decision: Decision

    # Errors/warnings
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def build_diagnostic(
    state: FinancialState,
    requested_amount: Decimal,
    safe_amount: Decimal,
    earliest_full_date: Optional[date],
    all_candidates: List[Candidate],
    decision: Decision,
    warnings: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
) -> RequestDiagnostic:
    """Build a diagnostic trace for a request."""
    return RequestDiagnostic(
        request_id=state.request_id,
        user_id=state.user_id,
        request_date=state.request_date,
        requested_amount=requested_amount,
        home_currency=state.home_currency,
        balance_before_pending=state.balance_before_pending,
        pending_debit_total=state.pending_debit_total,
        starting_balance=state.starting_balance,
        minimum_balance=state.minimum_balance,
        headroom=state.starting_balance - state.minimum_balance,
        future_debit_count=len(state.future_debits),
        future_income_count=len(state.future_income),
        recurring_debit_count=len(state.recurring_debits),
        recurring_income_count=len(state.recurring_income),
        safe_amount_no_changes=safe_amount,
        earliest_full_date=earliest_full_date,
        num_candidates=len(all_candidates),
        candidate_summaries=[
            f'{c.method} feasible={c.is_feasible} '
            f'total={c.total_payable:.2f} '
            f'first={c.first_payment_date} '
            f'changes={bool(c.spending_changes)}'
            for c in all_candidates
        ],
        decision=decision,
        warnings=warnings or [],
        errors=errors or [],
    )


def format_diagnostic(diag: RequestDiagnostic) -> str:
    """Format a diagnostic as a human-readable string."""
    lines = [
        f'=== {diag.request_id} ({diag.user_id}) ===',
        f'  Request date:    {diag.request_date}  Amount: {diag.requested_amount:.2f} {diag.home_currency}',
        f'  Balance:         {diag.balance_before_pending:.2f} (pending: -{diag.pending_debit_total:.2f}) => {diag.starting_balance:.2f}',
        f'  Min balance:     {diag.minimum_balance:.2f}  Headroom: {diag.headroom:.2f}',
        f'  Safe today:      {diag.safe_amount_no_changes:.2f}',
        f'  Earliest full:   {diag.earliest_full_date}',
        f'  Future debits:   {diag.future_debit_count}  Future income: {diag.future_income_count}',
        f'  Recurring debits:{diag.recurring_debit_count}  Recurring income: {diag.recurring_income_count}',
        f'  Candidates ({diag.num_candidates}):',
    ]
    for s in diag.candidate_summaries:
        lines.append(f'    {s}')
    d = diag.decision
    lines += [
        f'  DECISION:',
        f'    method:       {d.recommended_payment_method}',
        f'    affordability:{d.affordability_status}',
        f'    safe_amount:  {d.amount_safe_to_pay:.2f}',
        f'    plan:         {d.payment_plan}',
        f'    earliest:     {d.earliest_date_for_full_payment}',
        f'    changes:      {d.spending_changes_needed}',
    ]
    if diag.warnings:
        lines.append(f'  WARNINGS: {diag.warnings}')
    if diag.errors:
        lines.append(f'  ERRORS: {diag.errors}')
    return '\n'.join(lines)
