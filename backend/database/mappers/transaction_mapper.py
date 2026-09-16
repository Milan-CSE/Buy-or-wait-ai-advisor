"""
backend/database/mappers/transaction_mapper.py

Maps Transaction entity to and from CashflowEventInput domain DTO.
"""
from __future__ import annotations
from decimal import Decimal
import hashlib
import uuid

from backend.database.models.transaction import Transaction
from buyorwait_engine.domain.models import CashflowEventInput


class TransactionMapper:
    @staticmethod
    def to_domain_dto(entity: Transaction) -> CashflowEventInput:
        return CashflowEventInput(
            event_id=entity.external_transaction_id or str(entity.id),
            user_id=str(entity.user_id),
            event_type=entity.cash_type,
            description=entity.normalized_description or entity.original_description,
            category=entity.category,
            direction=entity.direction,
            amount=abs(entity.amount),
            currency=entity.currency,
            status=entity.lifecycle_status,
            settlement_date=entity.transaction_date,
            event_date=entity.posting_date or entity.transaction_date,
            flexibility=entity.flexibility,
            minimum_allowed_amount=entity.minimum_allowed_amount,
            linked_event_id=str(entity.linked_transaction_id) if entity.linked_transaction_id else None,
        )

    to_domain = to_domain_dto

    @staticmethod
    def compute_dedup_hash(user_id: uuid.UUID, tx_date: str, amount: Decimal, raw_desc: str) -> str:
        data = f"{user_id}:{tx_date}:{amount:.4f}:{raw_desc.strip().lower()}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def to_entity(
        dto: CashflowEventInput,
        user_id: uuid.UUID,
        account_id: uuid.UUID | None = None,
        import_batch_id: uuid.UUID | None = None,
    ) -> Transaction:
        amount_signed = dto.amount if dto.direction == 'credit' else -dto.amount
        dedup_hash = TransactionMapper.compute_dedup_hash(
            user_id,
            dto.settlement_date.isoformat() if dto.settlement_date else "",
            amount_signed,
            dto.description,
        )
        return Transaction(
            user_id=user_id,
            account_id=account_id,
            import_batch_id=import_batch_id,
            external_transaction_id=dto.event_id,
            dedup_hash=dedup_hash,
            transaction_date=dto.settlement_date or dto.event_date,
            posting_date=dto.event_date,
            amount=amount_signed,
            currency=dto.currency,
            amount_home=amount_signed,  # default 1:1, conversion done by FX service if needed
            direction=dto.direction,
            normalized_description=dto.description,
            original_description=dto.description,
            category=dto.category,
            lifecycle_status=dto.status,
            cash_type=dto.event_type,
            flexibility=dto.flexibility,
            minimum_allowed_amount=dto.minimum_allowed_amount,
            linked_transaction_id=uuid.UUID(dto.linked_event_id) if dto.linked_event_id else None,
        )
