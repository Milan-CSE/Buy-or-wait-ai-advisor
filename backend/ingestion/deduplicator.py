"""
backend/ingestion/deduplicator.py

File-level and transaction-level deduplication to prevent double-counting.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import hashlib
from typing import Optional, Set
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database.models.import_batch import ImportBatch
from backend.database.models.transaction import Transaction


class StatementDeduplicator:
    """
    Provides multi-tier deduplication:
    1. File level via content SHA-256 hash.
    2. In-batch transaction level via deterministic composite hash.
    3. Cross-batch database level via transaction dedup_hash.
    """

    @staticmethod
    def compute_transaction_hash(
        user_id: uuid.UUID,
        account_id: Optional[uuid.UUID],
        txn_date: date,
        amount: Decimal,
        normalized_description: str,
        external_id: Optional[str] = None,
    ) -> str:
        """
        Computes deterministic SHA-256 hash representing unique transaction occurrence.
        """
        if external_id and external_id.strip():
            raw_key = f"{user_id}:{external_id.strip()}"
        else:
            acc_str = str(account_id) if account_id else "no_acc"
            # Format amount strictly to 4 decimal places
            amt_str = f"{amount:.4f}"
            desc_str = normalized_description.lower().strip()
            raw_key = f"{user_id}:{acc_str}:{txn_date.isoformat()}:{amt_str}:{desc_str}"

        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @staticmethod
    def is_duplicate_file(session: Session, user_id: uuid.UUID, content_hash: str) -> Optional[ImportBatch]:
        """
        Checks if an identical file has already been ingested or verified for this user.
        """
        stmt = (
            select(ImportBatch)
            .where(
                ImportBatch.user_id == user_id,
                ImportBatch.content_hash == content_hash,
                ImportBatch.upload_status.in_(["committed", "verified", "parsed"]),
            )
        )
        return session.execute(stmt).scalars().first()

    @staticmethod
    def is_duplicate_transaction(session: Session, user_id: uuid.UUID, dedup_hash: str) -> bool:
        """
        Checks if a transaction with the given dedup_hash exists in the user's ledger.
        """
        stmt = (
            select(Transaction.id)
            .where(
                Transaction.user_id == user_id,
                Transaction.dedup_hash == dedup_hash,
            )
        )
        return session.execute(stmt).scalar_one_or_none() is not None
