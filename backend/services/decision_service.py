"""
backend/services/decision_service.py

Production application service orchestrating data loading, quality evaluation,
domain state adaptation, buyorwait_engine evaluation, and atomic audit persistence.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence, Union
import uuid

from sqlalchemy.orm import Session

from backend.database.mappers.decision_mapper import DecisionMapper
from backend.database.mappers.purchase_mapper import PurchaseMapper
from backend.database.models.account import FinancialAccount
from backend.database.models.audit import AuditEvent
from backend.database.models.decision import Decision
from backend.database.models.profile import FinancialProfile
from backend.database.models.purchase import PurchaseRequest
from backend.database.models.transaction import Transaction
from backend.database.repositories.account_repository import AccountRepository
from backend.database.repositories.audit_repository import AuditRepository
from backend.database.repositories.decision_repository import DecisionRepository
from backend.database.repositories.profile_repository import ProfileRepository
from backend.database.repositories.purchase_repository import PurchaseRepository
from backend.database.repositories.transaction_repository import TransactionRepository
from backend.services.data_quality import DataQualityEvaluator, DataQualityResult
from backend.services.errors import (
    DecisionEngineError,
    PersistenceError,
)
from backend.services.purchase_validator import PurchaseValidator
from backend.services.state_adapter import FinancialStateAdapter
from buyorwait_engine.currency.fx import FXEngine
from buyorwait_engine.domain.models import DecisionResult, PurchaseProposal
from buyorwait_engine.engine import BuyOrWaitEngine
from buyorwait_engine.risk.config import RiskCalibrationConfig, CURRENT_CALIBRATION_VERSION


ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class DecisionServiceResult:
    """Overall outcome of a purchase decision request."""
    is_sufficient: bool
    data_quality: DataQualityResult
    decision: Optional[DecisionResult] = None
    decision_record: Optional[Decision] = None
    audit_event: Optional[AuditEvent] = None
    purchase_request: Optional[PurchaseRequest] = None

    def to_dict(self) -> Dict[str, Any]:
        if not self.is_sufficient:
            return {
                "status": "DATA_INSUFFICIENT",
                "code": self.data_quality.code,
                "reason": self.data_quality.reason,
                "affected_data": self.data_quality.affected_data,
                "user_action_required": self.data_quality.user_action_required,
            }
        assert self.decision is not None
        out = {
            "status": "SUCCESS",
            "verdict": self.decision.verdict,
            "amount_safe_to_pay": str(self.decision.amount_safe_to_pay),
            "affordability_status": self.decision.affordability_status,
            "recommended_payment_method": self.decision.recommended_payment_method,
            "payment_plan": self.decision.payment_plan,
            "earliest_date_for_full_payment": (
                self.decision.earliest_date_for_full_payment.isoformat()
                if self.decision.earliest_date_for_full_payment else None
            ),
            "spending_changes_needed": self.decision.spending_changes_needed,
            "decision_explanation": self.decision.decision_explanation,
            "decision_id": str(self.decision_record.id) if self.decision_record else None,
            "purchase_request_id": str(self.purchase_request.id) if self.purchase_request else None,
        }
        if self.decision.risk_assessment:
            out["risk_assessment"] = self.decision.risk_assessment.to_dict()
        return out


class DecisionService:
    """
    Production-grade financial decision service coordinating validation,
    data quality checks, domain engine evaluation, and atomic persistence.
    """

    def __init__(
        self,
        session: Session,
        fx_engine: Optional[FXEngine] = None,
        engine: Optional[BuyOrWaitEngine] = None,
        data_quality_evaluator: Optional[DataQualityEvaluator] = None,
        state_adapter: Optional[FinancialStateAdapter] = None,
        risk_policy: str = "shadow_audit_only",
    ):
        self.session = session
        self.fx = fx_engine or FXEngine()
        self.risk_policy = risk_policy
        self.engine = engine or BuyOrWaitEngine(fx=self.fx, risk_policy=risk_policy)
        self.dq_evaluator = data_quality_evaluator or DataQualityEvaluator(fx_engine=self.fx)
        self.adapter = state_adapter or FinancialStateAdapter(fx_engine=self.fx)

    def evaluate_purchase(
        self,
        user_id: uuid.UUID,
        purchase_data: Union[PurchaseProposal, Dict[str, Any]],
        as_of_date: Optional[date] = None,
        save_to_db: bool = True,
    ) -> DecisionServiceResult:
        """
        Executes end-to-end evaluation for a purchase request:
        1. Validates purchase proposal constraints.
        2. Loads user profile, accounts, and transactions.
        3. Runs rigorous DataQualityEvaluator checks.
        4. If DATA_INSUFFICIENT, emits audit event and returns explanatory result.
        5. If OK, adapts financial state, executes buyorwait_engine.
        6. Atomically persists DecisionRecord and AuditEvent.
        """
        # Repositories scoped to user_id
        profile_repo = ProfileRepository(self.session, user_id)
        account_repo = AccountRepository(self.session, user_id)
        tx_repo = TransactionRepository(self.session, user_id)
        purchase_repo = PurchaseRepository(self.session, user_id)
        audit_repo = AuditRepository(self.session, user_id)

        # 1. Fetch user financial state
        profile = profile_repo.get_profile()
        accounts = account_repo.list_active()
        transactions = tx_repo.list_all_for_user()

        # 2. Validate and build PurchaseProposal
        if isinstance(purchase_data, PurchaseProposal):
            proposal = purchase_data
        else:
            proposal = PurchaseValidator.validate_and_build(
                purchase_data,
                user_id=str(user_id),
                max_installment_months=profile.max_installment_months if profile else None,
            )

        eval_date = as_of_date or proposal.request_date

        # 3. Data Quality & Completeness Evaluation
        dq_result = self.dq_evaluator.evaluate(
            profile=profile,
            accounts=accounts,
            transactions=transactions,
            as_of_date=eval_date,
            purchase_currency=proposal.currency,
        )

        if not dq_result.is_sufficient:
            # Log audit event for rejection with enhanced structured metadata
            audit_event = audit_repo.log(
                event_type="purchase_evaluation_rejected",
                actor_type="user",
                actor_id=str(user_id),
                structured_metadata={
                    "status": "DATA_INSUFFICIENT",
                    "rejection_code": "DATA_INSUFFICIENT",
                    "reason": dq_result.reason,
                    "reason_category": dq_result.affected_data,
                    "remediation_required": dq_result.user_action_required,
                    "request_id": proposal.request_id,
                    "engine_version": ENGINE_VERSION,
                    "decision_policy_version": self.risk_policy,
                },
            )
            if save_to_db:
                try:
                    self.session.commit()
                except Exception as e:
                    self.session.rollback()
                    raise PersistenceError(f"Failed to record data quality audit event: {e}")

            return DecisionServiceResult(
                is_sufficient=False,
                data_quality=dq_result,
                audit_event=audit_event,
            )

        # 4. State Adaptation
        assert profile is not None
        profile_input, domain_events = self.adapter.adapt(
            profile=profile,
            accounts=accounts,
            transactions=transactions,
            as_of_date=eval_date,
        )

        # 5. Domain Engine Evaluation
        try:
            decision_result = self.engine.evaluate(
                profile=profile_input,
                events=domain_events,
                purchase=proposal,
            )
        except Exception as e:
            raise DecisionEngineError(f"Financial decision engine evaluation failed: {e}")

        # 6. Persistence
        purchase_entity: Optional[PurchaseRequest] = None
        decision_entity: Optional[Decision] = None
        audit_event: Optional[AuditEvent] = None

        if save_to_db:
            try:
                # Create or persist PurchaseRequest entity
                purchase_entity = PurchaseMapper.to_entity(proposal, user_id)
                self.session.add(purchase_entity)
                self.session.flush()  # assign purchase_entity.id

                # Create Decision entity
                calib_ver = (
                    decision_result.risk_assessment.calibration_version
                    if decision_result.risk_assessment else CURRENT_CALIBRATION_VERSION
                )
                decision_entity = DecisionMapper.to_entity(
                    result=decision_result,
                    user_id=user_id,
                    purchase_request_id=purchase_entity.id,
                    engine_version=ENGINE_VERSION,
                    calibration_version=calib_ver,
                )
                self.session.add(decision_entity)

                # Record immutable audit event
                audit_event = audit_repo.log(
                    event_type="purchase_evaluated",
                    actor_type="user",
                    actor_id=str(user_id),
                    structured_metadata={
                        "purchase_request_id": str(purchase_entity.id),
                        "verdict": decision_result.verdict,
                        "amount_safe_to_pay": str(decision_result.amount_safe_to_pay),
                        "affordability_status": decision_result.affordability_status,
                        "recommended_payment_method": decision_result.recommended_payment_method,
                        "risk_tier": (
                            decision_result.risk_assessment.risk_tier
                            if decision_result.risk_assessment else "LOW_RISK"
                        ),
                        "engine_version": ENGINE_VERSION,
                        "calibration_version": calib_ver,
                        "decision_policy_version": self.risk_policy,
                    },
                )
                self.session.commit()
            except Exception as e:
                self.session.rollback()
                raise PersistenceError(f"Failed to persist decision and audit records: {e}")

        return DecisionServiceResult(
            is_sufficient=True,
            data_quality=dq_result,
            decision=decision_result,
            decision_record=decision_entity,
            audit_event=audit_event,
            purchase_request=purchase_entity,
        )
