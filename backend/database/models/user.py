"""
backend/database/models/user.py

User aggregate entity representing tenant identity.
"""
from __future__ import annotations
import uuid
from typing import Optional
from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, utc_now


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=True,
        default="",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",  # 'active', 'suspended', 'pending_verification'
    )

    # Relationships
    profile: Mapped["FinancialProfile"] = relationship(
        "FinancialProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    accounts: Mapped[list["FinancialAccount"]] = relationship(
        "FinancialAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    import_batches: Mapped[list["ImportBatch"]] = relationship(
        "ImportBatch",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    purchase_requests: Mapped[list["PurchaseRequest"]] = relationship(
        "PurchaseRequest",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision",
        back_populates="user",
        cascade="all, delete-orphan",
    )
