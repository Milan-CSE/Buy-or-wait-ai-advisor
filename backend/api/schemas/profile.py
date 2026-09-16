"""
backend/api/schemas/profile.py
"""
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field


class ProfileResponse(BaseModel):
    user_id: str
    home_currency: str = "USD"
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    protected_categories: List[str] = Field(default_factory=list)
    reducible_categories: List[str] = Field(default_factory=list)
    stoppable_categories: List[str] = Field(default_factory=list)
    payment_methods: List[str] = Field(default_factory=list)
    max_installment_months: Optional[Decimal] = None
    profile_version: int = 1


class ProfileUpdateRequest(BaseModel):
    home_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    current_available_balance: Optional[Decimal] = Field(default=None, ge=Decimal("0.00"))
    minimum_balance_to_keep: Optional[Decimal] = Field(default=None, ge=Decimal("0.00"))
    protected_categories: Optional[List[str]] = None
    reducible_categories: Optional[List[str]] = None
    stoppable_categories: Optional[List[str]] = None
    payment_methods: Optional[List[str]] = None
    max_installment_months: Optional[Decimal] = Field(default=None, ge=Decimal("0.00"))
