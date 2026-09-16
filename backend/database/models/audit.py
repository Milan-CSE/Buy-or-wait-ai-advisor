"""
backend/database/models/audit.py

Append-only, immutable audit trail for security, financial updates, and decisions.
"""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import String, DateTime, JSON, BigInteger, Integer, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from backend.database.session import Base
from backend.database.models.base import utc_now


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,  # 'purchase_evaluated', 'profile_updated', 'statement_imported'
    )
    actor_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="user",  # 'user', 'system', 'admin'
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )
    structured_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
