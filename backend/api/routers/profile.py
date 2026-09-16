"""
backend/api/routers/profile.py
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas.profile import ProfileResponse, ProfileUpdateRequest
from backend.database.models.user import User
from backend.database.repositories.profile_repository import ProfileRepository

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("", response_model=ProfileResponse, summary="Get user financial profile")
def get_profile(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ProfileResponse:
    """Returns the authenticated user's financial profile."""
    repo = ProfileRepository(session, current_user.id)
    profile = repo.get_profile()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Financial profile not found for user.",
        )
    return ProfileResponse(
        user_id=str(profile.user_id),
        home_currency=profile.home_currency,
        current_available_balance=profile.current_available_balance,
        minimum_balance_to_keep=profile.minimum_balance_to_keep,
        protected_categories=list(profile.protected_categories or []),
        reducible_categories=list(profile.reducible_categories or []),
        stoppable_categories=list(profile.stoppable_categories or []),
        payment_methods=list(profile.payment_methods or []),
        max_installment_months=profile.max_installment_months,
        profile_version=profile.profile_version,
    )


@router.put("", response_model=ProfileResponse, summary="Create or update user financial profile")
def update_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ProfileResponse:
    """Updates or initializes the authenticated user's financial profile."""
    repo = ProfileRepository(session, current_user.id)
    existing = repo.get_profile()

    home_curr = body.home_currency or (existing.home_currency if existing else "USD")
    cur_bal = body.current_available_balance if body.current_available_balance is not None else (existing.current_available_balance if existing else 0)
    min_keep = body.minimum_balance_to_keep if body.minimum_balance_to_keep is not None else (existing.minimum_balance_to_keep if existing else 0)
    protected = body.protected_categories if body.protected_categories is not None else (existing.protected_categories if existing else [])
    reducible = body.reducible_categories if body.reducible_categories is not None else (existing.reducible_categories if existing else [])
    stoppable = body.stoppable_categories if body.stoppable_categories is not None else (existing.stoppable_categories if existing else [])
    methods = body.payment_methods if body.payment_methods is not None else (existing.payment_methods if existing else ["full_payment", "installments", "partial_payment"])
    max_inst = body.max_installment_months if body.max_installment_months is not None else (existing.max_installment_months if existing else None)

    updated = repo.save_or_update(
        home_currency=home_curr,
        current_available_balance=cur_bal,
        minimum_balance_to_keep=min_keep,
        protected_categories=protected,
        reducible_categories=reducible,
        stoppable_categories=stoppable,
        payment_methods=methods,
        max_installment_months=max_inst,
    )
    session.commit()

    return ProfileResponse(
        user_id=str(updated.user_id),
        home_currency=updated.home_currency,
        current_available_balance=updated.current_available_balance,
        minimum_balance_to_keep=updated.minimum_balance_to_keep,
        protected_categories=list(updated.protected_categories or []),
        reducible_categories=list(updated.reducible_categories or []),
        stoppable_categories=list(updated.stoppable_categories or []),
        payment_methods=list(updated.payment_methods or []),
        max_installment_months=updated.max_installment_months,
        profile_version=updated.profile_version,
    )
