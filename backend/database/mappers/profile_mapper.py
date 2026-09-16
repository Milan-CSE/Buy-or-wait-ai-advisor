"""
backend/database/mappers/profile_mapper.py

Maps FinancialProfile entity to and from FinancialProfileInput domain DTO.
"""
from __future__ import annotations
from decimal import Decimal
import uuid

from backend.database.models.profile import FinancialProfile
from buyorwait_engine.domain.models import FinancialProfileInput


class ProfileMapper:
    @staticmethod
    def to_domain_dto(entity: FinancialProfile) -> FinancialProfileInput:
        return FinancialProfileInput(
            user_id=str(entity.user_id),
            home_currency=entity.home_currency,
            current_available_balance=entity.current_available_balance,
            minimum_balance_to_keep=entity.minimum_balance_to_keep,
            protected_categories=tuple(entity.protected_categories or []),
            reducible_categories=tuple(entity.reducible_categories or []),
            stoppable_categories=tuple(entity.stoppable_categories or []),
            payment_methods=tuple(entity.payment_methods or []),
            max_installment_months=entity.max_installment_months,
        )

    to_domain = to_domain_dto

    @staticmethod
    def to_entity(dto: FinancialProfileInput, user_id: uuid.UUID) -> FinancialProfile:
        return FinancialProfile(
            user_id=user_id,
            home_currency=dto.home_currency,
            current_available_balance=dto.current_available_balance,
            minimum_balance_to_keep=dto.minimum_balance_to_keep,
            protected_categories=list(dto.protected_categories),
            reducible_categories=list(dto.reducible_categories),
            stoppable_categories=list(dto.stoppable_categories),
            payment_methods=list(dto.payment_methods),
            max_installment_months=dto.max_installment_months,
        )
