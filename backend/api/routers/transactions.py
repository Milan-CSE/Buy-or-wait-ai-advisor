"""
backend/api/routers/transactions.py
"""
from datetime import date
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas.transaction import TransactionListResponse, TransactionResponse
from backend.database.models.transaction import Transaction
from backend.database.models.user import User

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.get("", response_model=TransactionListResponse, summary="List transactions with filters and pagination")
def list_transactions(
    start_date: Optional[date] = Query(None, description="Filter transactions on or after this date"),
    end_date: Optional[date] = Query(None, description="Filter transactions on or before this date"),
    category: Optional[str] = Query(None, description="Filter by transaction category"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Records per page"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> TransactionListResponse:
    """Lists transactions owned by the authenticated tenant with filtering and pagination."""
    query = select(Transaction).where(Transaction.user_id == current_user.id)

    if start_date:
        query = query.where(Transaction.transaction_date >= start_date)
    if end_date:
        query = query.where(Transaction.transaction_date <= end_date)
    if category:
        query = query.where(Transaction.category == category)

    # Count total
    count_stmt = select(func.count()).select_from(query.subquery())
    total = session.execute(count_stmt).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    items_stmt = query.order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).offset(offset).limit(page_size)
    records = session.execute(items_stmt).scalars().all()

    items = [
        TransactionResponse(
            id=str(t.id),
            account_id=str(t.account_id) if t.account_id else None,
            transaction_date=t.transaction_date,
            posting_date=t.posting_date,
            amount=t.amount,
            currency=t.currency,
            amount_home=t.amount_home,
            direction=t.direction,
            normalized_description=t.normalized_description,
            category=t.category,
            lifecycle_status=t.lifecycle_status,
            cash_type=t.cash_type,
            confidence_state=t.confidence_state,
        )
        for t in records
    ]

    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return TransactionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
