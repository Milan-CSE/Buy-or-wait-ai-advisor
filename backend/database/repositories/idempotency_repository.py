"""
backend/database/repositories/idempotency_repository.py

Tenant-scoped repository for IdempotencyRecord entities.
"""
from __future__ import annotations
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.idempotency import IdempotencyRecord
from backend.database.repositories.base import TenantScopedRepository


class IdempotencyRepository(TenantScopedRepository[IdempotencyRecord]):
    def __init__(self, session: Session, user_id: uuid.UUID):
        super().__init__(session, user_id, IdempotencyRecord)

    def get_by_key(self, idempotency_key: str) -> Optional[IdempotencyRecord]:
        stmt = select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == self.user_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def record(
        self,
        idempotency_key: str,
        request_hash: str,
        status_code: int,
        response_body: dict,
    ) -> IdempotencyRecord:
        rec = IdempotencyRecord(
            user_id=self.user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status_code=status_code,
            response_body=response_body,
        )
        self.session.add(rec)
        return rec
