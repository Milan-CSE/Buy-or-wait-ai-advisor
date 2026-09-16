"""
backend/database/repositories/transaction_repository.py

Tenant-isolated repository for Transaction entities.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.transaction import Transaction
from backend.database.repositories.base import TenantScopedRepository


class TransactionRepository(TenantScopedRepository[Transaction]):
    def __init__(self, session: Session, user_id: uuid.UUID):
        super().__init__(session, user_id, Transaction)

    def get_by_dedup_hash(self, dedup_hash: str) -> Optional[Transaction]:
        stmt = select(Transaction).where(
            Transaction.user_id == self.user_id,
            Transaction.dedup_hash == dedup_hash,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_date_range(self, start_date: date, end_date: date) -> Sequence[Transaction]:
        """Fetch chronological transactions for cashflow evaluation."""
        stmt = select(Transaction).where(
            Transaction.user_id == self.user_id,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
        ).order_by(Transaction.transaction_date.asc())
        return self.session.execute(stmt).scalars().all()

    def list_all_for_user(self) -> Sequence[Transaction]:
        stmt = select(Transaction).where(
            Transaction.user_id == self.user_id
        ).order_by(Transaction.transaction_date.asc())
        return self.session.execute(stmt).scalars().all()

    # Alias for convenience
    get_events_for_period = list_by_date_range
