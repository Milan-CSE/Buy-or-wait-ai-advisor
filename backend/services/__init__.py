"""
backend/services package

Production application services: data quality evaluation, state adaptation, and decision orchestration.
"""
from backend.services.errors import (
    ServiceError,
    DataInsufficientError,
    InvalidPurchaseError,
    FinancialStateInvalidError,
    UnsupportedCurrencyError,
    DecisionEngineError,
    PersistenceError,
)
from backend.services.data_quality import DataQualityEvaluator, DataQualityResult
from backend.services.purchase_validator import PurchaseValidator
from backend.services.state_adapter import FinancialStateAdapter
from backend.services.decision_service import DecisionService, DecisionServiceResult

__all__ = [
    "ServiceError",
    "DataInsufficientError",
    "InvalidPurchaseError",
    "FinancialStateInvalidError",
    "UnsupportedCurrencyError",
    "DecisionEngineError",
    "PersistenceError",
    "DataQualityEvaluator",
    "DataQualityResult",
    "PurchaseValidator",
    "FinancialStateAdapter",
    "DecisionService",
    "DecisionServiceResult",
]
