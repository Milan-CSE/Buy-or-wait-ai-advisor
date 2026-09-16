"""
backend/api/schemas/account.py
"""
from decimal import Decimal
from typing import List
from pydantic import BaseModel


class AccountResponse(BaseModel):
    id: str
    account_type: str
    institution_name: str
    account_mask: str
    currency: str
    current_balance: Decimal
    status: str


class AccountListResponse(BaseModel):
    items: List[AccountResponse]
    total: int
