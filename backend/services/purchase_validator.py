"""
backend/services/purchase_validator.py

Validates purchase proposal inputs prior to domain engine evaluation.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import re
from typing import Any, Dict, List, Optional, Sequence

from backend.services.errors import InvalidPurchaseError
from buyorwait_engine.domain.models import PurchaseProposal, PaymentOptionInput


class PurchaseValidator:
    """
    Validates and constructs PurchaseProposal domain DTOs.
    """

    @classmethod
    def validate_and_build(
        cls,
        data: Dict[str, Any],
        user_id: str,
        request_id: Optional[str] = None,
        max_installment_months: Optional[Decimal] = None,
    ) -> PurchaseProposal:
        """
        Validates raw or parsed input dictionary and returns a strict PurchaseProposal DTO.
        """
        # 1. Amount validation
        raw_amt = data.get("requested_amount")
        if raw_amt is None:
            raise InvalidPurchaseError("Requested purchase amount is required.", field_name="requested_amount")
        try:
            amt = Decimal(str(raw_amt))
        except Exception:
            raise InvalidPurchaseError(f"Invalid requested_amount '{raw_amt}'. Must be a valid numeric value.", field_name="requested_amount")
        if amt <= Decimal("0.00"):
            raise InvalidPurchaseError(f"Requested purchase amount must be strictly positive, got {amt}.", field_name="requested_amount")

        # 2. Currency validation
        currency = str(data.get("currency", "USD")).strip().upper()
        if not re.match(r"^[A-Z]{3}$", currency):
            raise InvalidPurchaseError(f"Invalid currency code '{currency}'. Must be a 3-letter ISO code.", field_name="currency")

        # 3. Date validation
        raw_req_dt = data.get("request_date")
        if raw_req_dt is None:
            raise InvalidPurchaseError("request_date is required.", field_name="request_date")
        if isinstance(raw_req_dt, str):
            try:
                req_dt = date.fromisoformat(raw_req_dt)
            except Exception:
                raise InvalidPurchaseError(f"Invalid request_date format '{raw_req_dt}'. Use YYYY-MM-DD.", field_name="request_date")
        elif isinstance(raw_req_dt, date):
            req_dt = raw_req_dt
        else:
            raise InvalidPurchaseError("request_date must be a date or ISO string.", field_name="request_date")

        raw_comp_dt = data.get("desired_completion_date")
        if raw_comp_dt is None:
            comp_dt = req_dt
        elif isinstance(raw_comp_dt, str):
            try:
                comp_dt = date.fromisoformat(raw_comp_dt)
            except Exception:
                raise InvalidPurchaseError(f"Invalid desired_completion_date format '{raw_comp_dt}'. Use YYYY-MM-DD.", field_name="desired_completion_date")
        elif isinstance(raw_comp_dt, date):
            comp_dt = raw_comp_dt
        else:
            raise InvalidPurchaseError("desired_completion_date must be a date or ISO string.", field_name="desired_completion_date")

        if comp_dt < req_dt:
            raise InvalidPurchaseError(
                f"desired_completion_date ({comp_dt}) cannot be earlier than request_date ({req_dt}).",
                field_name="desired_completion_date"
            )

        allows_partial = bool(data.get("allows_partial_payment", True))
        item_desc = str(data.get("item_description", "")).strip()
        merchant = str(data.get("merchant_name", "")).strip()
        category = str(data.get("category", "")).strip()

        # 4. Payment options validation
        raw_options = data.get("payment_options", [])
        parsed_options: List[PaymentOptionInput] = []

        for idx, opt in enumerate(raw_options):
            opt_id = str(opt.get("payment_option_id", f"opt_{idx+1}"))
            p_type = str(opt.get("payment_type", "installment")).strip().lower()
            if p_type not in ("full_payment", "installment"):
                p_type = "installment"

            try:
                n_payments = int(opt.get("number_of_payments", 1))
            except Exception:
                raise InvalidPurchaseError(f"Invalid number_of_payments in option {opt_id}.", field_name="payment_options")
            if n_payments < 1:
                raise InvalidPurchaseError(f"number_of_payments in option {opt_id} must be >= 1.", field_name="payment_options")

            first_dt_raw = opt.get("first_payment_date")
            first_dt: Optional[date] = None
            if first_dt_raw:
                if isinstance(first_dt_raw, str):
                    try:
                        first_dt = date.fromisoformat(first_dt_raw)
                    except Exception:
                        pass
                elif isinstance(first_dt_raw, date):
                    first_dt = first_dt_raw

            try:
                inst_amt = Decimal(str(opt.get("installment_amount", "0")))
            except Exception:
                inst_amt = Decimal("0")
            try:
                tot_amt = Decimal(str(opt.get("total_amount", "0")))
            except Exception:
                tot_amt = Decimal("0")
            try:
                rate = Decimal(str(opt.get("interest_rate_pct", "0")))
            except Exception:
                rate = Decimal("0")

            parsed_options.append(PaymentOptionInput(
                payment_option_id=opt_id,
                payment_type=p_type,
                number_of_payments=n_payments,
                first_payment_date=first_dt or req_dt,
                installment_amount=inst_amt,
                total_amount=tot_amt if tot_amt > Decimal("0") else amt,
                interest_rate_pct=rate,
                payment_frequency_days=opt.get("payment_frequency_days"),
            ))

        return PurchaseProposal(
            request_id=request_id or str(data.get("request_id", "")),
            user_id=user_id,
            requested_amount=amt,
            currency=currency,
            request_date=req_dt,
            desired_completion_date=comp_dt,
            allows_partial_payment=allows_partial,
            item_description=item_desc,
            merchant_name=merchant,
            category=category,
            payment_options=parsed_options,
        )
