"""
backend/api/routers/purchases.py
"""
import hashlib
import json
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, get_db, get_decision_service
from backend.api.schemas.purchase import PurchaseEvaluationRequest
from backend.api.schemas.decision import (
    GroundedExplanationSchema,
    PurchaseEvaluationResponse,
    RiskAssessmentSchema,
)
from backend.database.models.user import User
from backend.database.repositories.idempotency_repository import IdempotencyRepository
from backend.observability.metrics import get_metrics
from backend.services.decision_service import DecisionService
from backend.services.explanation_service import ExplanationService

router = APIRouter(prefix="/purchases", tags=["Purchases & Decisioning"])


@router.post("/evaluate", response_model=PurchaseEvaluationResponse, summary="Evaluate purchase proposal affordability")
def evaluate_purchase(
    body: PurchaseEvaluationRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    service: DecisionService = Depends(get_decision_service),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    Evaluates proposed purchase affordability against the user's verified financial position.
    Runs DataQualityEvaluator, FinancialStateAdapter, and BuyOrWaitEngine.
    Supports PostgreSQL-backed idempotency replay via X-Idempotency-Key.
    """
    idem_repo = IdempotencyRepository(session, current_user.id)
    payload_raw = body.model_dump_json()
    req_hash = hashlib.sha256(payload_raw.encode("utf-8")).hexdigest()

    # 1. Check idempotency cache
    if x_idempotency_key:
        cached = idem_repo.get_by_key(x_idempotency_key)
        if cached:
            if cached.request_hash == req_hash:
                return JSONResponse(
                    status_code=cached.status_code,
                    content=cached.response_body,
                    headers={"X-Cache": "HIT", "Idempotent-Replay": "true"},
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key reused with conflicting request payload.",
                )

    # 2. Execute decision service
    purchase_data = body.model_dump()
    result = service.evaluate_purchase(
        user_id=current_user.id,
        purchase_data=purchase_data,
        save_to_db=True,
    )

    # 3. Handle DATA_INSUFFICIENT
    if not result.is_sufficient:
        # Record metric
        get_metrics().record_data_insufficient(result.data_quality.reason)

        grounded_data_exp = ExplanationService.explain_data_insufficient(result.data_quality)

        error_payload = {
            "type": "https://api.buyorwait.com/errors/data-insufficient",
            "title": "Data Insufficient",
            "status": 422,
            "detail": result.data_quality.reason,
            "instance": "/api/v1/purchases/evaluate",
            "code": "DATA_INSUFFICIENT",
            "error": {
                "code": "DATA_INSUFFICIENT",
                "message": result.data_quality.reason,
                "affected_data": result.data_quality.affected_data,
                "user_action_required": result.data_quality.user_action_required,
                "grounded_explanation": grounded_data_exp.to_dict(),
            },
        }
        if x_idempotency_key:
            idem_repo.record(
                idempotency_key=x_idempotency_key,
                request_hash=req_hash,
                status_code=422,
                response_body=error_payload,
            )
            session.commit()

        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=error_payload)

    # 4. Format success response
    assert result.decision is not None
    assert result.decision_record is not None
    dec = result.decision
    rec = result.decision_record

    # Record decision metrics
    metrics = get_metrics()
    metrics.record_decision(
        verdict=dec.verdict,
        affordability_status=dec.affordability_status,
        recommended_payment_method=dec.recommended_payment_method,
        risk_tier=dec.risk_assessment.risk_tier if dec.risk_assessment else "LOW_RISK",
        amount=float(body.requested_amount),
    )

    risk_schema = None
    if dec.risk_assessment:
        risk_schema = RiskAssessmentSchema(
            risk_tier=dec.risk_assessment.risk_tier,
            safe_amount_p50=dec.risk_assessment.safe_amount_p50,
            safe_amount_p90=dec.risk_assessment.safe_amount_p90,
            minimum_balance_p50=dec.risk_assessment.minimum_balance_p50,
            minimum_balance_p90=dec.risk_assessment.minimum_balance_p90,
            headroom_p50=dec.risk_assessment.headroom_p50,
            headroom_p90=dec.risk_assessment.headroom_p90,
            risk_reason=dec.risk_assessment.risk_reason,
            stress_summary=dec.risk_assessment.stress_summary,
            calibration_version=dec.risk_assessment.calibration_version,
            p90_breach_detected=dec.risk_assessment.p90_breach_detected,
        )

    # Generate Grounded Explanation
    grounded_exp = ExplanationService.explain_decision(
        decision=dec,
        requested_amount=body.requested_amount,
        currency=body.currency,
        minimum_balance=None,
    )
    grounded_schema = GroundedExplanationSchema(
        headline=grounded_exp.headline,
        concise_explanation=grounded_exp.concise_explanation,
        supporting_facts=grounded_exp.supporting_facts,
        risk_explanation=grounded_exp.risk_explanation,
        suggested_action=grounded_exp.suggested_action,
    )

    resp = PurchaseEvaluationResponse(
        decision_id=str(rec.id),
        purchase_request_id=str(rec.purchase_request_id),
        verdict=dec.verdict,
        affordability_status=dec.affordability_status,
        amount_safe_to_pay=dec.amount_safe_to_pay,
        recommended_payment_method=dec.recommended_payment_method,
        payment_plan=dec.payment_plan,
        earliest_date_for_full_payment=dec.earliest_date_for_full_payment,
        spending_changes_needed=dec.spending_changes_needed,
        decision_explanation=dec.decision_explanation,
        risk_tier=dec.risk_assessment.risk_tier if dec.risk_assessment else "LOW_RISK",
        risk_assessment=risk_schema,
        grounded_explanation=grounded_schema,
        engine_version=rec.engine_version,
        calibration_version=rec.calibration_version,
        created_at=rec.created_at,
    )

    if x_idempotency_key:
        idem_repo.record(
            idempotency_key=x_idempotency_key,
            request_hash=req_hash,
            status_code=200,
            response_body=json.loads(resp.model_dump_json()),
        )
        session.commit()

    return resp
