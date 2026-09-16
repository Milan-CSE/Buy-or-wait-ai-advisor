"""
backend/api/schemas/transaction.py
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel
from backend.api.schemas.common import PaginatedResponse


class TransactionResponse(BaseModel):
    id: str
    account_id: Optional[str] = None
    transaction_date: date
    posting_date: Optional[date] = None
    amount: Decimal
    currency: str
    amount_home: Decimal
    direction: str
    normalized_description: str
    category: str
    lifecycle_status: str
    cash_type: str
    confidence_state: str


class TransactionListResponse(PaginatedResponse[TransactionResponse]):
    pass
