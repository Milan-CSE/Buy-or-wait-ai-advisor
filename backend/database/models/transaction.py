"""
backend/database/models/transaction.py

Persistent transaction entity preserving cashflow classification and audit integrity.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import uuid
from sqlalchemy import String, Numeric, Date, Text, Uuid, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, TenantOwnedMixin


class Transaction(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "transactions"

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
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_transaction_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    dedup_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    transaction_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    posting_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    amount_home: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(
        String(16),
        nullable=False,  # 'debit', 'credit', 'non_cash'
    )
    normalized_description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )
    original_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="settled",  # 'settled', 'pending', 'scheduled', 'cancelled', 'failed', 'unrealized'
    )
    cash_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="immediate_debit",  # 'immediate_debit', 'future_debit', 'settled_income', 'confirmed_income', 'non_cash', 'void'
    )
    flexibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="fixed",  # 'fixed', 'reducible', 'stoppable', 'reducible_or_stoppable'
    )
    minimum_allowed_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=True,
    )
    linked_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_provenance: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="statement_import",
    )
    confidence_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="verified",  # 'verified', 'inferred', 'needs_review'
    )

    user: Mapped["User"] = relationship("User", back_populates="transactions")
    account: Mapped["FinancialAccount | None"] = relationship("FinancialAccount", back_populates="transactions")
    import_batch: Mapped["ImportBatch | None"] = relationship("ImportBatch", back_populates="transactions")

    __table_args__ = (
        Index("ix_user_tx_date", "user_id", "transaction_date"),
        Index("ix_user_dedup", "user_id", "dedup_hash"),
    )
