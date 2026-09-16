"""
backend/services/errors.py

Application-level error model for financial state adaptation, data quality, and decisioning.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


class ServiceError(Exception):
    """Base class for all service-level errors."""
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code,
            "message": self.message,
        }


class DataInsufficientError(ServiceError):
    """Raised when user data is inadequate to make a reliable decision without guessing."""
    def __init__(
        self,
        reason: str,
        affected_data: str,
        user_action_required: str,
    ):
        super().__init__(reason, code="DATA_INSUFFICIENT")
        self.reason = reason
        self.affected_data = affected_data
        self.user_action_required = user_action_required

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code,
            "reason": self.reason,
            "affected_data": self.affected_data,
            "user_action_required": self.user_action_required,
        }


class InvalidPurchaseError(ServiceError):
    """Raised when a proposed purchase fails validation constraints."""
    def __init__(self, message: str, field_name: Optional[str] = None):
        super().__init__(message, code="INVALID_PURCHASE")
        self.field_name = field_name

    def to_dict(self) -> Dict[str, Any]:
        res = super().to_dict()
        if self.field_name:
            res["field"] = self.field_name
        return res


class FinancialStateInvalidError(ServiceError):
    """Raised when financial profile or account data is logically contradictory."""
    def __init__(self, message: str):
        super().__init__(message, code="FINANCIAL_STATE_INVALID")


class UnsupportedCurrencyError(ServiceError):
    """Raised when an account or purchase uses an unsupported or unconvertible currency."""
    def __init__(self, currency: str, reason: str = "No exchange rate available"):
        super().__init__(f"Unsupported or unconvertible currency '{currency}': {reason}", code="UNSUPPORTED_CURRENCY")
        self.currency = currency


class DecisionEngineError(ServiceError):
    """Raised when the domain engine encounters an unrecoverable failure during evaluation."""
    def __init__(self, message: str):
        super().__init__(message, code="DECISION_ENGINE_ERROR")


class PersistenceError(ServiceError):
    """Raised when decision or audit logging fails to commit to storage."""
    def __init__(self, message: str):
        super().__init__(message, code="PERSISTENCE_ERROR")
