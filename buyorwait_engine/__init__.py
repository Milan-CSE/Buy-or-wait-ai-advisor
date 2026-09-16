"""
buyorwait_engine

Commercial Financial Decision Support Library.
Evaluates proposed purchases against conservative cash-flow projections and P90 risk buffers.
"""
from buyorwait_engine.domain.enums import (
    Verdict,
    AffordabilityStatus,
    PaymentMethod,
    RiskTier,
    CashType,
    Flexibility,
    Cadence,
)
from buyorwait_engine.domain.models import (
    PaymentOptionInput,
    PurchaseProposal,
    FinancialProfileInput,
    CashflowEventInput,
    RiskAssessmentResult,
    DecisionResult,
)
from buyorwait_engine.domain.state import FinancialState, ScheduledItem, LifecycleEvent
from buyorwait_engine.currency.fx import FXEngine, FXRateMissingError
from buyorwait_engine.recurrence.cadence import infer_recurring_streams, RecurringStream
from buyorwait_engine.forecast.ledger import build_ledger, Ledger, DayEntry
from buyorwait_engine.decision.safe_amount import compute_safe_amount, is_plan_safe
from buyorwait_engine.decision.earliest_date import find_earliest_full_payment_date
from buyorwait_engine.decision.candidates import Candidate, generate_candidates
from buyorwait_engine.decision.ranker import Decision, make_decision, select_best_candidate
from buyorwait_engine.risk.config import (
    CURRENT_CALIBRATION_VERSION,
    DEFAULT_P90_STRESS_FACTORS,
    RiskCalibrationConfig,
)
from buyorwait_engine.risk.classifier import RiskProfile, classify_risk
from buyorwait_engine.risk.stress_buffers import build_stressed_state
from buyorwait_engine.risk.policy import apply_risk_policy
from buyorwait_engine.state.builder import build_financial_state_from_inputs, resolve_events
from buyorwait_engine.engine import evaluate_purchase, BuyOrWaitEngine

__version__ = "1.0.0"

__all__ = [
    'Verdict',
    'AffordabilityStatus',
    'PaymentMethod',
    'RiskTier',
    'CashType',
    'Flexibility',
    'Cadence',
    'PaymentOptionInput',
    'PurchaseProposal',
    'FinancialProfileInput',
    'CashflowEventInput',
    'RiskAssessmentResult',
    'DecisionResult',
    'FinancialState',
    'ScheduledItem',
    'LifecycleEvent',
    'FXEngine',
    'FXRateMissingError',
    'infer_recurring_streams',
    'RecurringStream',
    'build_ledger',
    'Ledger',
    'DayEntry',
    'compute_safe_amount',
    'is_plan_safe',
    'find_earliest_full_payment_date',
    'Candidate',
    'generate_candidates',
    'Decision',
    'make_decision',
    'select_best_candidate',
    'CURRENT_CALIBRATION_VERSION',
    'DEFAULT_P90_STRESS_FACTORS',
    'RiskCalibrationConfig',
    'RiskProfile',
    'classify_risk',
    'build_stressed_state',
    'apply_risk_policy',
    'build_financial_state_from_inputs',
    'resolve_events',
    'evaluate_purchase',
    'BuyOrWaitEngine',
]
