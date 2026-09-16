"""
backend/database/models/purchase.py

Purchase request submitted by a user for affordability evaluation.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import uuid
from sqlalchemy import String, Numeric, Date, Boolean, JSON, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, TenantOwnedMixin


class PurchaseRequest(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "purchase_requests"

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
    requested_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    request_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    desired_completion_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    allows_partial_payment: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    item_description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )
    merchant_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    payment_options_data: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    user: Mapped["User"] = relationship("User", back_populates="purchase_requests")
    decision: Mapped["Decision"] = relationship(
        "Decision",
        back_populates="purchase_request",
        uselist=False,
        cascade="all, delete-orphan",
    )
