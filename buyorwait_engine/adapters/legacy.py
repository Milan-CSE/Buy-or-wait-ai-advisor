"""
buyorwait_engine/adapters/legacy.py

Bridges existing competition Dataset and Request structures to the clean domain library.
Ensures zero breakage for existing benchmark runs and backtests.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Any, List, Optional, Sequence

from buyorwait_engine.domain.models import (
    FinancialProfileInput,
    CashflowEventInput,
    PurchaseProposal,
    PaymentOptionInput,
)


def adapt_profile(profile: Any) -> FinancialProfileInput:
    """Converts legacy data_loader.FinancialProfile into FinancialProfileInput."""
    return FinancialProfileInput(
        user_id=profile.user_id,
        home_currency=profile.home_currency,
        current_available_balance=profile.current_available_balance,
        minimum_balance_to_keep=profile.minimum_balance_to_keep,
        financial_priorities=tuple(getattr(profile, 'financial_priorities', ())),
        protected_categories=tuple(getattr(profile, 'protected_categories', ())),
        reducible_categories=tuple(getattr(profile, 'reducible_categories', ())),
        stoppable_categories=tuple(getattr(profile, 'stoppable_categories', ())),
        payment_methods=tuple(getattr(profile, 'payment_methods', ())),
        max_installment_months=profile.max_installment_months,
    )


def adapt_event(event: Any) -> CashflowEventInput:
    """Converts legacy data_loader.FinancialEvent into CashflowEventInput."""
    return CashflowEventInput(
        event_id=event.event_id,
        user_id=event.user_id,
        event_type=event.event_type,
        description=event.description or '',
        category=event.category,
        direction=event.direction,
        amount=event.amount,
        currency=event.currency,
        status=event.status,
        settlement_date=event.settlement_date,
        event_date=event.event_date,
        flexibility=event.flexibility or 'fixed',
        minimum_allowed_amount=event.minimum_allowed_amount,
        linked_event_id=event.linked_event_id,
    )


def adapt_payment_option(opt: Any) -> PaymentOptionInput:
    """Converts legacy data_loader.PaymentOption into PaymentOptionInput."""
    amt = getattr(opt, 'payment_amount', getattr(opt, 'installment_amount', None))
    tot = getattr(opt, 'total_payable_amount', getattr(opt, 'total_amount', None))
    method = getattr(opt, 'payment_method', getattr(opt, 'payment_type', 'installments'))
    return PaymentOptionInput(
        payment_option_id=opt.payment_option_id,
        payment_type=method,
        number_of_payments=opt.number_of_payments,
        first_payment_date=opt.first_payment_date,
        installment_amount=amt,
        total_amount=tot,
        interest_rate_pct=getattr(opt, 'interest_rate_pct', getattr(opt, 'financing_fee', Decimal('0'))),
        payment_frequency_days=opt.payment_frequency_days,
    )


def adapt_request(req: Any, dataset: Optional[Any] = None) -> PurchaseProposal:
    """Converts legacy data_loader.Request into PurchaseProposal."""
    options: List[PaymentOptionInput] = []
    if dataset and hasattr(dataset, 'payment_options'):
        raw_opts = dataset.payment_options.get(req.request_id, [])
        options = [adapt_payment_option(o) for o in raw_opts]

    curr = getattr(req, 'currency', '')
    if not curr and dataset and hasattr(dataset, 'profiles') and req.user_id in dataset.profiles:
        curr = dataset.profiles[req.user_id].home_currency

    return PurchaseProposal(
        request_id=req.request_id,
        user_id=req.user_id,
        requested_amount=req.requested_amount,
        currency=curr or 'USD',
        request_date=req.request_date,
        desired_completion_date=req.desired_completion_date,
        allows_partial_payment=getattr(req, 'allows_partial_payment', True),
        item_category=getattr(req, 'request_type', ''),
        payment_options=options,
    )
