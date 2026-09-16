"""
backend/database/repositories/account_repository.py

Tenant-isolated repository for FinancialAccount entities.
"""
from __future__ import annotations
from decimal import Decimal
import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.account import FinancialAccount
from backend.database.repositories.base import TenantScopedRepository


class AccountRepository(TenantScopedRepository[FinancialAccount]):
    def __init__(self, session: Session, user_id: uuid.UUID):
        super().__init__(session, user_id, FinancialAccount)

    def list_active(self) -> Sequence[FinancialAccount]:
        stmt = select(FinancialAccount).where(
            FinancialAccount.user_id == self.user_id,
            FinancialAccount.status == "active",
        )
        return self.session.execute(stmt).scalars().all()

    def create(
        self,
        account_type: str,
        institution_name: str,
        account_mask: str,
        currency: str = "USD",
        current_balance: Decimal = Decimal("0.0000"),
    ) -> FinancialAccount:
        acc = FinancialAccount(
            user_id=self.user_id,
            account_type=account_type,
            institution_name=institution_name,
            account_mask=account_mask,
            currency=currency,
            current_balance=current_balance,
            status="active",
        )
        self.session.add(acc)
        return acc
