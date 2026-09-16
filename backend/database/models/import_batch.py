"""
backend/database/models/import_batch.py

Import batch record tracking provenance and status of ingested files.
"""
from __future__ import annotations
import uuid
from sqlalchemy import String, Integer, Text, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database.session import Base
from backend.database.models.base import TimestampMixin, TenantOwnedMixin


class ImportBatch(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "import_batches"

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
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="csv_statement",  # 'csv_statement', 'ofx', 'open_banking', 'manual'
    )
    upload_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",  # 'pending', 'processing', 'completed', 'failed'
    )
    parsing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="parsed",
    )
    verification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="verified",  # 'verified', 'unverified', 'rejected'
    )
    total_rows: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    imported_rows: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="import_batches")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="import_batch",
    )
