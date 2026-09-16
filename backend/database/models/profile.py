"""
backend/database/models/profile.py

User financial profile and solvency configuration.
"""
from __future__ import annotations
from decimal import Decimal
import uuid
from sqlalchemy import String, Numeric, Uuid, ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, TenantOwnedMixin


class FinancialProfile(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "financial_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    home_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    current_available_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    minimum_balance_to_keep: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    reserve_policy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="strict_minimum",
    )
    protected_categories: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    reducible_categories: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    stoppable_categories: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    payment_methods: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["full_payment", "installments", "partial_payment"],
    )
    max_installment_months: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2, asdecimal=True),
        nullable=True,
    )
    profile_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    user: Mapped["User"] = relationship("User", back_populates="profile")
