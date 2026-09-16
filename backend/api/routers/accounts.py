"""
backend/api/routers/accounts.py
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas.account import AccountListResponse, AccountResponse
from backend.database.models.user import User
from backend.database.repositories.account_repository import AccountRepository

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.get("", response_model=AccountListResponse, summary="List user financial accounts")
def list_accounts(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> AccountListResponse:
    """Returns all active accounts belonging to the authenticated tenant."""
    repo = AccountRepository(session, current_user.id)
    accounts = repo.list_active()
    items = [
        AccountResponse(
            id=str(a.id),
            account_type=a.account_type,
            institution_name=a.institution_name,
            account_mask=a.account_mask,
            currency=a.currency,
            current_balance=a.current_balance,
            status=a.status,
        )
        for a in accounts
    ]
    return AccountListResponse(items=items, total=len(items))


@router.get("/{account_id}", response_model=AccountResponse, summary="Get account details")
def get_account(
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> AccountResponse:
    """Returns a specific account by ID, isolated to the authenticated user."""
    repo = AccountRepository(session, current_user.id)
    acc = repo.get_by_id(account_id)
    if not acc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found.",
        )
    return AccountResponse(
        id=str(acc.id),
        account_type=acc.account_type,
        institution_name=acc.institution_name,
        account_mask=acc.account_mask,
        currency=acc.currency,
        current_balance=acc.current_balance,
        status=acc.status,
    )
