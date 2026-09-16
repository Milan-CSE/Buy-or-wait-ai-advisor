"""
backend/database/models/account.py

Individual bank accounts, credit lines, or cash repositories.
"""
from __future__ import annotations
from decimal import Decimal
import uuid
from sqlalchemy import String, Numeric, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, TenantOwnedMixin


class FinancialAccount(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "financial_accounts"

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
    account_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,  # 'checking', 'savings', 'credit_card', 'cash'
    )
    institution_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
    )
    account_mask: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    current_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",  # 'active', 'closed'
    )

    user: Mapped["User"] = relationship("User", back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="account",
        cascade="all, delete-orphan",
    )
