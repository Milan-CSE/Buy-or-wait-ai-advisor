"""
backend/database/repositories/base.py

Base tenant-isolated repository enforcement.
"""
from __future__ import annotations
import uuid
from typing import Generic, TypeVar, Optional, Sequence
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from backend.database.session import Base

T = TypeVar("T", bound=Base)


class TenantAccessError(PermissionError):
    """Raised when an operation attempts to access or mutate cross-tenant data."""


class TenantScopedRepository(Generic[T]):
    """
    Base repository that strictly scopes all database operations to a specific user_id.
    """
    def __init__(self, session: Session, user_id: uuid.UUID, model_cls: type[T]):
        self.session = session
        self.user_id = user_id
        self.model_cls = model_cls

    def get_by_id(self, entity_id: uuid.UUID) -> Optional[T]:
        """Fetch by primary key, strictly scoped to this tenant."""
        stmt = select(self.model_cls).where(
            self.model_cls.id == entity_id,
            self.model_cls.user_id == self.user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        """List records scoped to this tenant."""
        stmt = select(self.model_cls).where(
            self.model_cls.user_id == self.user_id
        ).limit(limit).offset(offset)
        return self.session.execute(stmt).scalars().all()

    def add(self, entity: T) -> T:
        """Add record, asserting tenant ownership."""
        if getattr(entity, "user_id", None) != self.user_id:
            raise TenantAccessError(
                f"Cannot add entity with user_id {getattr(entity, 'user_id', None)} "
                f"to repository scoped to user_id {self.user_id}"
            )
        self.session.add(entity)
        return entity

    def delete_by_id(self, entity_id: uuid.UUID) -> bool:
        """Delete record strictly belonging to this tenant."""
        existing = self.get_by_id(entity_id)
        if existing is None:
            # Check if record exists under another tenant to raise security error
            foreign = self.session.execute(
                select(self.model_cls).where(self.model_cls.id == entity_id)
            ).scalar_one_or_none()
            if foreign is not None:
                raise TenantAccessError(
                    f"Tenant {self.user_id} unauthorized to delete entity {entity_id} "
                    f"belonging to tenant {foreign.user_id}"
                )
            return False

        self.session.delete(existing)
        return True
