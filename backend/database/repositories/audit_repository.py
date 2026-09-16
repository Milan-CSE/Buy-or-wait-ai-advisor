"""
backend/database/repositories/audit_repository.py

Tenant-isolated repository for immutable AuditEvent records.
"""
from __future__ import annotations
import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.audit import AuditEvent


class AuditRepository:
    def __init__(self, session: Session, user_id: uuid.UUID):
        self.session = session
        self.user_id = user_id

    def log(
        self,
        event_type: str,
        actor_type: str = "user",
        actor_id: str | None = None,
        structured_metadata: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            user_id=self.user_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            structured_metadata=structured_metadata or {},
        )
        self.session.add(event)
        return event

    def list_events(self, limit: int = 100) -> Sequence[AuditEvent]:
        stmt = select(AuditEvent).where(
            AuditEvent.user_id == self.user_id
        ).order_by(AuditEvent.timestamp.desc()).limit(limit)
        return self.session.execute(stmt).scalars().all()
