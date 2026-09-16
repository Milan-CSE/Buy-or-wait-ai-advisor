"""
backend/database/models/idempotency.py

PostgreSQL-backed idempotency record preventing duplicate submissions
and ensuring deterministic replays for financial operations.
"""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import String, Integer, JSON, Uuid, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, TenantOwnedMixin


class IdempotencyRecord(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status_code: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    response_body: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_user_idempotency_key", "user_id", "idempotency_key", unique=True),
    )
