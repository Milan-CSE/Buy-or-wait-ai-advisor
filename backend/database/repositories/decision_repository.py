"""
backend/database/repositories/decision_repository.py

Tenant-isolated repository for Decision entities.
"""
from __future__ import annotations
import uuid
from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.decision import Decision
from backend.database.repositories.base import TenantScopedRepository


class DecisionRepository(TenantScopedRepository[Decision]):
    def __init__(self, session: Session, user_id: uuid.UUID):
        super().__init__(session, user_id, Decision)

    def get_by_purchase_id(self, purchase_request_id: uuid.UUID) -> Optional[Decision]:
        stmt = select(Decision).where(
            Decision.user_id == self.user_id,
            Decision.purchase_request_id == purchase_request_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_history(self) -> Sequence[Decision]:
        stmt = select(Decision).where(
            Decision.user_id == self.user_id
        ).order_by(Decision.created_at.desc())
        return self.session.execute(stmt).scalars().all()
