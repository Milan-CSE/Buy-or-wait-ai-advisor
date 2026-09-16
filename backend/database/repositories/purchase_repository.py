"""
backend/database/repositories/purchase_repository.py

Tenant-isolated repository for PurchaseRequest entities.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import uuid
from typing import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.purchase import PurchaseRequest
from backend.database.repositories.base import TenantScopedRepository


class PurchaseRepository(TenantScopedRepository[PurchaseRequest]):
    def __init__(self, session: Session, user_id: uuid.UUID):
        super().__init__(session, user_id, PurchaseRequest)

    def create(
        self,
        requested_amount: Decimal,
        currency: str,
        request_date: date,
        desired_completion_date: date,
        allows_partial_payment: bool = True,
        item_description: str = "",
        merchant_name: str = "",
        category: str = "",
        payment_options_data: list | None = None,
    ) -> PurchaseRequest:
        req = PurchaseRequest(
            user_id=self.user_id,
            requested_amount=requested_amount,
            currency=currency,
            request_date=request_date,
            desired_completion_date=desired_completion_date,
            allows_partial_payment=allows_partial_payment,
            item_description=item_description,
            merchant_name=merchant_name,
            category=category,
            payment_options_data=payment_options_data or [],
        )
        self.session.add(req)
        return req

    def list_history(self) -> Sequence[PurchaseRequest]:
        stmt = select(PurchaseRequest).where(
            PurchaseRequest.user_id == self.user_id
        ).order_by(PurchaseRequest.created_at.desc())
        return self.session.execute(stmt).scalars().all()
