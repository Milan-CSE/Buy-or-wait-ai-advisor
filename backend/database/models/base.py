"""
backend/database/models/base.py

Base model conventions and common mixins.
"""
from __future__ import annotations
from datetime import datetime, timezone
import uuid
from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from backend.database.session import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Provides created_at and updated_at timestamps in UTC."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class TenantOwnedMixin:
    """Enforces explicit tenant (user) ownership."""
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
