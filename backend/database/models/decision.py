"""
backend/database/models/decision.py

Evaluated decision result with risk analysis, audit parameters, and grounded rationale.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import uuid
from sqlalchemy import String, Numeric, Date, Boolean, Text, JSON, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, TenantOwnedMixin


class Decision(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "decisions"

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
    purchase_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("purchase_requests.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    engine_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="1.0.0",
    )
    calibration_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="v3_empirical_q90_20260914",
    )
    verdict: Mapped[str] = mapped_column(
        String(32),
        nullable=False,  # 'BUY', 'SAFER_PAYMENT', 'WAIT', 'NOT_RECOMMENDED'
    )
    amount_safe_to_pay: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
    )
    affordability_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    recommended_payment_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    payment_plan: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="none",
    )
    earliest_date_for_full_payment: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    spending_changes_needed: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="none",
    )
    decision_explanation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    risk_tier: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="LOW_RISK",
    )
    safe_amount_p50: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    safe_amount_p90: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    minimum_balance_p50: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    minimum_balance_p90: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    headroom_p50: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    headroom_p90: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True),
        nullable=False,
        default=Decimal("0.0000"),
    )
    risk_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    stress_summary: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="none",
    )
    p90_breach_detected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    audit_metrics: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    user: Mapped["User"] = relationship("User", back_populates="decisions")
    purchase_request: Mapped["PurchaseRequest"] = relationship("PurchaseRequest", back_populates="decision")
