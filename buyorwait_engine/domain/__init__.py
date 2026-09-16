"""
buyorwait_engine/domain package.
"""
from buyorwait_engine.domain.enums import (
    AffordabilityStatus,
    Cadence,
    CashType,
    Flexibility,
    PaymentMethod,
    RiskTier,
    Verdict,
)
from buyorwait_engine.domain.models import (
    CashflowEventInput,
    DecisionResult,
    FinancialProfileInput,
    PaymentOptionInput,
    PurchaseProposal,
    RiskAssessmentResult,
)
from buyorwait_engine.domain.state import (
    FIXED_CATEGORIES,
    FORECAST_HORIZON_DAYS,
    FinancialState,
    LifecycleEvent,
    SALARY_TERMINATION_KEYWORDS,
    ScheduledItem,
    VARIABLE_CATEGORIES,
)

__all__ = [
    'AffordabilityStatus',
    'Cadence',
    'CashType',
    'CashflowEventInput',
    'DecisionResult',
    'FIXED_CATEGORIES',
    'FORECAST_HORIZON_DAYS',
    'FinancialProfileInput',
    'FinancialState',
    'Flexibility',
    'LifecycleEvent',
    'PaymentMethod',
    'PaymentOptionInput',
    'PurchaseProposal',
    'RiskAssessmentResult',
    'RiskTier',
    'SALARY_TERMINATION_KEYWORDS',
    'ScheduledItem',
    'VARIABLE_CATEGORIES',
    'Verdict',
]
