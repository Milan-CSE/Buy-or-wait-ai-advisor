"""
backend/database/mappers/purchase_mapper.py

Maps PurchaseRequest entity to and from PurchaseProposal domain DTO.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import uuid

from backend.database.models.purchase import PurchaseRequest
from buyorwait_engine.domain.models import PurchaseProposal, PaymentOptionInput


class PurchaseMapper:
    @staticmethod
    def to_domain_dto(entity: PurchaseRequest) -> PurchaseProposal:
        options = []
        for raw in entity.payment_options_data or []:
            f_dt = date.fromisoformat(raw["first_payment_date"]) if raw.get("first_payment_date") else None
            options.append(PaymentOptionInput(
                payment_option_id=raw.get("payment_option_id", ""),
                payment_type=raw.get("payment_type", "installment"),
                number_of_payments=int(raw.get("number_of_payments", 1)),
                first_payment_date=f_dt,
                installment_amount=Decimal(str(raw.get("installment_amount", "0"))),
                total_amount=Decimal(str(raw.get("total_amount", "0"))),
                interest_rate_pct=Decimal(str(raw.get("interest_rate_pct", "0"))),
                payment_frequency_days=raw.get("payment_frequency_days"),
            ))

        return PurchaseProposal(
            request_id=str(entity.id),
            user_id=str(entity.user_id),
            requested_amount=entity.requested_amount,
            currency=entity.currency,
            request_date=entity.request_date,
            desired_completion_date=entity.desired_completion_date,
            allows_partial_payment=entity.allows_partial_payment,
            item_description=entity.item_description,
            merchant_name=entity.merchant_name,
            category=entity.category,
            payment_options=options,
        )

    @staticmethod
    def to_entity(dto: PurchaseProposal, user_id: uuid.UUID) -> PurchaseRequest:
        raw_options = []
        for opt in dto.payment_options:
            raw_options.append({
                "payment_option_id": opt.payment_option_id,
                "payment_type": opt.payment_type,
                "number_of_payments": opt.number_of_payments,
                "first_payment_date": opt.first_payment_date.isoformat() if opt.first_payment_date else None,
                "installment_amount": str(opt.installment_amount),
                "total_amount": str(opt.total_amount),
                "interest_rate_pct": str(opt.interest_rate_pct),
                "payment_frequency_days": opt.payment_frequency_days,
            })

        return PurchaseRequest(
            user_id=user_id,
            requested_amount=dto.requested_amount,
            currency=dto.currency,
            request_date=dto.request_date,
            desired_completion_date=dto.desired_completion_date,
            allows_partial_payment=dto.allows_partial_payment,
            item_description=dto.item_description,
            merchant_name=dto.merchant_name,
            category=dto.category,
            payment_options_data=raw_options,
        )
