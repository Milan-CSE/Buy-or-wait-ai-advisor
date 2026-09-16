"""
backend/api/schemas/decision.py
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from backend.api.schemas.common import PaginatedResponse


class RiskAssessmentSchema(BaseModel):
    risk_tier: str
    safe_amount_p50: Decimal
    safe_amount_p90: Decimal
    minimum_balance_p50: Decimal
    minimum_balance_p90: Decimal
    headroom_p50: Decimal
    headroom_p90: Decimal
    risk_reason: str
    stress_summary: str
    calibration_version: str
    p90_breach_detected: bool


class GroundedExplanationSchema(BaseModel):
    headline: str
    concise_explanation: str
    supporting_facts: Dict[str, Any]
    risk_explanation: str
    suggested_action: str


class PurchaseEvaluationResponse(BaseModel):
    decision_id: str
    purchase_request_id: str
    verdict: str
    affordability_status: str
    amount_safe_to_pay: Decimal
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[date] = None
    spending_changes_needed: str
    decision_explanation: str
    risk_tier: str
    risk_assessment: Optional[RiskAssessmentSchema] = None
    grounded_explanation: Optional[GroundedExplanationSchema] = None
    engine_version: str
    calibration_version: str
    created_at: datetime


class DecisionListResponse(PaginatedResponse[PurchaseEvaluationResponse]):
    pass
