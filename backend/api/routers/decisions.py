"""
backend/api/routers/decisions.py
"""
import math
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas.decision import DecisionListResponse, PurchaseEvaluationResponse, RiskAssessmentSchema
from backend.database.models.decision import Decision
from backend.database.models.user import User
from backend.database.repositories.decision_repository import DecisionRepository

router = APIRouter(prefix="/decisions", tags=["Decisions"])


@router.get("", response_model=DecisionListResponse, summary="List user decision history")
def list_decisions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Records per page"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> DecisionListResponse:
    """Lists historical decisions evaluated for the authenticated tenant."""
    query = select(Decision).where(Decision.user_id == current_user.id)

    count_stmt = select(func.count()).select_from(query.subquery())
    total = session.execute(count_stmt).scalar() or 0

    offset = (page - 1) * page_size
    items_stmt = query.order_by(Decision.created_at.desc()).offset(offset).limit(page_size)
    records = session.execute(items_stmt).scalars().all()

    items = []
    for d in records:
        risk_schema = RiskAssessmentSchema(
            risk_tier=d.risk_tier,
            safe_amount_p50=d.safe_amount_p50,
            safe_amount_p90=d.safe_amount_p90,
            minimum_balance_p50=d.minimum_balance_p50,
            minimum_balance_p90=d.minimum_balance_p90,
            headroom_p50=d.headroom_p50,
            headroom_p90=d.headroom_p90,
            risk_reason=d.risk_reason,
            stress_summary=d.stress_summary,
            calibration_version=d.calibration_version,
            p90_breach_detected=d.p90_breach_detected,
        )
        items.append(PurchaseEvaluationResponse(
            decision_id=str(d.id),
            purchase_request_id=str(d.purchase_request_id),
            verdict=d.verdict,
            affordability_status=d.affordability_status,
            amount_safe_to_pay=d.amount_safe_to_pay,
            recommended_payment_method=d.recommended_payment_method,
            payment_plan=d.payment_plan,
            earliest_date_for_full_payment=d.earliest_date_for_full_payment,
            spending_changes_needed=d.spending_changes_needed,
            decision_explanation=d.decision_explanation,
            risk_tier=d.risk_tier,
            risk_assessment=risk_schema,
            engine_version=d.engine_version,
            calibration_version=d.calibration_version,
            created_at=d.created_at,
        ))

    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return DecisionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{decision_id}", response_model=PurchaseEvaluationResponse, summary="Get decision details")
def get_decision(
    decision_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> PurchaseEvaluationResponse:
    """Returns a specific decision result isolated to the authenticated tenant."""
    repo = DecisionRepository(session, current_user.id)
    d = repo.get_by_id(decision_id)
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision record not found.")

    risk_schema = RiskAssessmentSchema(
        risk_tier=d.risk_tier,
        safe_amount_p50=d.safe_amount_p50,
        safe_amount_p90=d.safe_amount_p90,
        minimum_balance_p50=d.minimum_balance_p50,
        minimum_balance_p90=d.minimum_balance_p90,
        headroom_p50=d.headroom_p50,
        headroom_p90=d.headroom_p90,
        risk_reason=d.risk_reason,
        stress_summary=d.stress_summary,
        calibration_version=d.calibration_version,
        p90_breach_detected=d.p90_breach_detected,
    )
    return PurchaseEvaluationResponse(
        decision_id=str(d.id),
        purchase_request_id=str(d.purchase_request_id),
        verdict=d.verdict,
        affordability_status=d.affordability_status,
        amount_safe_to_pay=d.amount_safe_to_pay,
        recommended_payment_method=d.recommended_payment_method,
        payment_plan=d.payment_plan,
        earliest_date_for_full_payment=d.earliest_date_for_full_payment,
        spending_changes_needed=d.spending_changes_needed,
        decision_explanation=d.decision_explanation,
        risk_tier=d.risk_tier,
        risk_assessment=risk_schema,
        engine_version=d.engine_version,
        calibration_version=d.calibration_version,
        created_at=d.created_at,
    )
