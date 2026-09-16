"""
buyorwait_engine/decision

Plan generation, spending optimization, safe payment calculation,
earliest safe date detection, and candidate ranking.
"""
from buyorwait_engine.decision.safe_amount import compute_safe_amount, compute_safe_amount_if_paid_on, is_plan_safe
from buyorwait_engine.decision.earliest_date import find_earliest_full_payment_date
from buyorwait_engine.decision.spending import (
    SpendingChangeOption,
    get_eligible_changes,
    enumerate_spending_change_combos,
    format_spending_changes,
)
from buyorwait_engine.decision.candidates import Candidate, generate_candidates
from buyorwait_engine.decision.ranker import Decision, make_decision, select_best_candidate

__all__ = [
    'compute_safe_amount',
    'compute_safe_amount_if_paid_on',
    'is_plan_safe',
    'find_earliest_full_payment_date',
    'SpendingChangeOption',
    'get_eligible_changes',
    'enumerate_spending_change_combos',
    'format_spending_changes',
    'Candidate',
    'generate_candidates',
    'Decision',
    'make_decision',
    'select_best_candidate',
]
