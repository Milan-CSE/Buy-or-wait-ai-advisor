"""
backend/database/mappers/decision_mapper.py

Maps DecisionResult domain DTO to Decision ORM entity for audit persistence.
"""
from __future__ import annotations
from decimal import Decimal
import uuid

from backend.database.models.decision import Decision
from buyorwait_engine.domain.models import DecisionResult


class DecisionMapper:
    @staticmethod
    def to_entity(
        result: DecisionResult,
        user_id: uuid.UUID,
        purchase_request_id: uuid.UUID,
        engine_version: str = "1.0.0",
        calibration_version: str = "v3_empirical_q90_20260914",
    ) -> Decision:
        risk = result.risk_assessment
        return Decision(
            user_id=user_id,
            purchase_request_id=purchase_request_id,
            engine_version=engine_version,
            calibration_version=risk.calibration_version if risk else calibration_version,
            verdict=result.verdict,
            amount_safe_to_pay=result.amount_safe_to_pay,
            affordability_status=result.affordability_status,
            recommended_payment_method=result.recommended_payment_method,
            payment_plan=result.payment_plan,
            earliest_date_for_full_payment=result.earliest_date_for_full_payment,
            spending_changes_needed=result.spending_changes_needed,
            decision_explanation=result.decision_explanation,
            risk_tier=risk.risk_tier if risk else "LOW_RISK",
            safe_amount_p50=risk.safe_amount_p50 if risk else Decimal("0.0000"),
            safe_amount_p90=risk.safe_amount_p90 if risk else Decimal("0.0000"),
            minimum_balance_p50=risk.minimum_balance_p50 if risk else Decimal("0.0000"),
            minimum_balance_p90=risk.minimum_balance_p90 if risk else Decimal("0.0000"),
            headroom_p50=risk.headroom_p50 if risk else Decimal("0.0000"),
            headroom_p90=risk.headroom_p90 if risk else Decimal("0.0000"),
            risk_reason=risk.risk_reason if risk else "",
            stress_summary=risk.stress_summary if risk else "none",
            p90_breach_detected=risk.p90_breach_detected if risk else False,
            audit_metrics=result.audit_metrics or {},
        )
