"""
buyorwait_engine/domain/models.py

Explicit input and output Data Transfer Objects (DTOs) for the
Buy or Wait? financial decision engine.
All numeric amounts use Decimal; all dates use datetime.date.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Sequence

from buyorwait_engine.domain.enums import (
    AffordabilityStatus,
    PaymentMethod,
    RiskTier,
    Verdict,
)


@dataclass(frozen=True)
class PaymentOptionInput:
    """A financing or payment option available for a purchase."""
    payment_option_id: str
    payment_type: str                  # 'full_payment' | 'installment'
    number_of_payments: int
    first_payment_date: Optional[date] = None
    installment_amount: Decimal = Decimal('0')
    total_amount: Decimal = Decimal('0')
    interest_rate_pct: Decimal = Decimal('0')
    payment_frequency_days: Optional[int] = None
    financing_fee: Decimal = Decimal('0')

    def __post_init__(self):
        for attr, val in [
            ('installment_amount', self.installment_amount),
            ('total_amount', self.total_amount),
            ('interest_rate_pct', self.interest_rate_pct),
            ('financing_fee', self.financing_fee),
        ]:
            if val is not None and not isinstance(val, Decimal):
                raise TypeError(f"{attr} must be Decimal, got {type(val).__name__}")


@dataclass(frozen=True)
class PurchaseProposal:
    """A proposed purchase submitted for affordability evaluation."""
    request_id: str
    user_id: str
    requested_amount: Decimal
    currency: str
    request_date: date
    desired_completion_date: date
    allows_partial_payment: bool = True
    item_description: str = ""
    merchant_name: str = ""
    category: str = ""
    item_category: str = ""
    payment_options: List[PaymentOptionInput] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.requested_amount, Decimal):
            raise TypeError(f"requested_amount must be Decimal, got {type(self.requested_amount).__name__}")
        if self.requested_amount <= Decimal('0'):
            raise ValueError(f"requested_amount must be strictly positive, got {self.requested_amount}")
        if self.desired_completion_date < self.request_date:
            raise ValueError(
                f"desired_completion_date ({self.desired_completion_date}) cannot be earlier than "
                f"request_date ({self.request_date})"
            )
        if not self.category and self.item_category:
            object.__setattr__(self, 'category', self.item_category)


@dataclass(frozen=True)
class FinancialProfileInput:
    """User balance, emergency buffer, and category preferences."""
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: Sequence[str] = ()
    protected_categories: Sequence[str] = ()
    reducible_categories: Sequence[str] = ()
    stoppable_categories: Sequence[str] = ()
    payment_methods: Sequence[str] = ()
    payment_methods_accepted: Sequence[str] = ()
    max_installment_months: Optional[Decimal] = None

    def __post_init__(self):
        if not isinstance(self.current_available_balance, Decimal):
            raise TypeError(
                f"current_available_balance must be Decimal, got {type(self.current_available_balance).__name__}"
            )
        if not isinstance(self.minimum_balance_to_keep, Decimal):
            raise TypeError(
                f"minimum_balance_to_keep must be Decimal, got {type(self.minimum_balance_to_keep).__name__}"
            )
        if self.minimum_balance_to_keep < Decimal('0'):
            raise ValueError(
                f"minimum_balance_to_keep cannot be negative, got {self.minimum_balance_to_keep}"
            )
        if self.max_installment_months is not None and not isinstance(self.max_installment_months, Decimal):
            raise TypeError(
                f"max_installment_months must be Decimal, got {type(self.max_installment_months).__name__}"
            )
        # Harmonize payment_methods
        if not self.payment_methods and self.payment_methods_accepted:
            object.__setattr__(self, 'payment_methods', tuple(self.payment_methods_accepted))
        elif not self.payment_methods_accepted and self.payment_methods:
            object.__setattr__(self, 'payment_methods_accepted', tuple(self.payment_methods))


@dataclass(frozen=True)
class CashflowEventInput:
    """An individual historical, pending, or scheduled financial transaction."""
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str           # 'debit' | 'credit' | 'non_cash'
    amount: Decimal
    currency: str
    status: str              # 'settled' | 'pending' | 'scheduled' | 'cancelled' | 'failed' | 'unrealized'
    settlement_date: Optional[date] = None
    event_date: Optional[date] = None
    flexibility: str = 'fixed'
    minimum_allowed_amount: Optional[Decimal] = None
    linked_event_id: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"amount must be Decimal, got {type(self.amount).__name__}")
        if self.minimum_allowed_amount is not None and not isinstance(self.minimum_allowed_amount, Decimal):
            raise TypeError(
                f"minimum_allowed_amount must be Decimal, got {type(self.minimum_allowed_amount).__name__}"
            )


@dataclass(frozen=True)
class RiskAssessmentResult:
    """Empirical P90 stress evaluation details."""
    risk_tier: str           # 'LOW_RISK' | 'MODERATE_RISK' | 'HIGH_RISK'
    safe_amount_p50: Decimal
    safe_amount_p90: Decimal
    minimum_balance_p50: Decimal
    minimum_balance_p90: Decimal
    headroom_p50: Decimal
    headroom_p90: Decimal
    risk_reason: str
    stress_summary: str
    calibration_version: str
    p90_breach_detected: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'risk_tier': self.risk_tier,
            'safe_amount_p50': float(self.safe_amount_p50),
            'safe_amount_p90': float(self.safe_amount_p90),
            'minimum_balance_p50': float(self.minimum_balance_p50),
            'minimum_balance_p90': float(self.minimum_balance_p90),
            'headroom_p50': float(self.headroom_p50),
            'headroom_p90': float(self.headroom_p90),
            'risk_reason': self.risk_reason,
            'stress_summary': self.stress_summary,
            'calibration_version': self.calibration_version,
            'p90_breach_detected': self.p90_breach_detected,
        }


@dataclass(frozen=True)
class DecisionResult:
    """The complete decision recommendation returned by the engine."""
    request_id: str
    verdict: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str          # 'none' or 'YYYY-MM-DD:amt|...'
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str   # 'none' or 'stop:X|reduce_to:Y:Z'
    decision_explanation: str
    risk_assessment: Optional[RiskAssessmentResult] = None
    audit_metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = {
            'request_id': self.request_id,
            'verdict': self.verdict,
            'amount_safe_to_pay': f"{self.amount_safe_to_pay:.2f}",
            'affordability_status': self.affordability_status,
            'recommended_payment_method': self.recommended_payment_method,
            'payment_plan': self.payment_plan,
            'earliest_date_for_full_payment': (
                self.earliest_date_for_full_payment.isoformat()
                if self.earliest_date_for_full_payment else ''
            ),
            'spending_changes_needed': self.spending_changes_needed,
            'decision_explanation': self.decision_explanation,
        }
        if self.risk_assessment:
            out['risk_assessment'] = self.risk_assessment.to_dict()
        return out
