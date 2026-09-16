"""
backend/database/repositories/profile_repository.py

Tenant-isolated repository for FinancialProfile.
"""
from __future__ import annotations
from decimal import Decimal
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.profile import FinancialProfile
from backend.database.repositories.base import TenantAccessError, TenantScopedRepository


class ProfileRepository(TenantScopedRepository[FinancialProfile]):
    def __init__(self, session: Session, user_id: uuid.UUID):
        super().__init__(session, user_id, FinancialProfile)

    def get_profile(self) -> Optional[FinancialProfile]:
        """Fetch the unique profile for this tenant."""
        stmt = select(FinancialProfile).where(FinancialProfile.user_id == self.user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def save_or_update(
        self,
        home_currency: str = "USD",
        current_available_balance: Decimal = Decimal("0.0000"),
        minimum_balance_to_keep: Decimal = Decimal("0.0000"),
        protected_categories: list[str] | None = None,
        reducible_categories: list[str] | None = None,
        stoppable_categories: list[str] | None = None,
        payment_methods: list[str] | None = None,
        max_installment_months: Decimal | None = None,
    ) -> FinancialProfile:
        existing = self.get_profile()
        if existing:
            existing.home_currency = home_currency
            existing.current_available_balance = current_available_balance
            existing.minimum_balance_to_keep = minimum_balance_to_keep
            existing.protected_categories = protected_categories or []
            existing.reducible_categories = reducible_categories or []
            existing.stoppable_categories = stoppable_categories or []
            existing.payment_methods = payment_methods or ["full_payment", "installments", "partial_payment"]
            existing.max_installment_months = max_installment_months
            existing.profile_version += 1
            return existing

        profile = FinancialProfile(
            user_id=self.user_id,
            home_currency=home_currency,
            current_available_balance=current_available_balance,
            minimum_balance_to_keep=minimum_balance_to_keep,
            protected_categories=protected_categories or [],
            reducible_categories=reducible_categories or [],
            stoppable_categories=stoppable_categories or [],
            payment_methods=payment_methods or ["full_payment", "installments", "partial_payment"],
            max_installment_months=max_installment_months,
            profile_version=1,
        )
        self.session.add(profile)
        return profile
