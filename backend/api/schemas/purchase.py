"""
backend/api/schemas/purchase.py
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class PaymentOptionSchema(BaseModel):
    payment_option_id: str = Field(..., description="Unique provider option identifier.")
    payment_type: str = Field(default="installment", description="'full_payment' or 'installment'")
    number_of_payments: int = Field(default=1, ge=1, description="Count of installment installments.")
    first_payment_date: Optional[date] = Field(default=None, description="Initial payment date.")
    installment_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    total_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    interest_rate_pct: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    payment_frequency_days: Optional[int] = Field(default=None, ge=1)


class PurchaseEvaluationRequest(BaseModel):
    item_description: str = Field(..., min_length=1, max_length=255, description="Item or service being evaluated.")
    requested_amount: Decimal = Field(..., gt=Decimal("0.00"), description="Purchase amount (must be positive).")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="3-letter currency code.")
    request_date: date = Field(..., description="Proposed transaction evaluation date.")
    desired_completion_date: Optional[date] = Field(default=None, description="Deadline for completing purchase.")
    allows_partial_payment: bool = Field(default=True, description="Whether partial payments are accepted.")
    merchant_name: str = Field(default="", max_length=255)
    category: str = Field(default="", max_length=64)
    payment_options: List[PaymentOptionSchema] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        code = v.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(f"Invalid currency code '{v}'. Must be 3 alphabetic characters.")
        return code

    @field_validator("desired_completion_date")
    @classmethod
    def validate_dates(cls, v: Optional[date], info) -> Optional[date]:
        req_dt = info.data.get("request_date")
        if v is not None and req_dt is not None and v < req_dt:
            raise ValueError(f"desired_completion_date ({v}) cannot be earlier than request_date ({req_dt}).")
        return v
