"""
backend/ingestion/models.py

Data transfer objects, enums, and domain representations for financial statement ingestion.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class IngestionState(str, Enum):
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    COMMITTED = "committed"
    FAILED = "failed"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class TransactionDirection(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    NON_CASH = "non_cash"


@dataclass(frozen=True)
class RawStatementFile:
    user_id: uuid.UUID
    account_id: Optional[uuid.UUID]
    filename: str
    content_hash: str
    file_size_bytes: int
    raw_content: bytes
    quarantine_path: Optional[str] = None


@dataclass
class ParsedRow:
    line_number: int
    raw_fields: Dict[str, str]
    date_str: Optional[str] = None
    description_str: Optional[str] = None
    amount_str: Optional[str] = None
    debit_str: Optional[str] = None
    credit_str: Optional[str] = None
    currency_str: Optional[str] = None
    category_str: Optional[str] = None
    balance_str: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedTransaction:
    user_id: uuid.UUID
    account_id: Optional[uuid.UUID]
    import_batch_id: uuid.UUID
    line_number: int
    transaction_date: date
    amount: Decimal
    direction: str  # 'debit', 'credit', 'non_cash'
    currency: str
    normalized_description: str
    original_description: str
    category: str
    category_reason: str
    is_internal_transfer: bool
    dedup_hash: str
    verification_status: VerificationStatus
    confidence_state: str  # 'verified', 'inferred', 'needs_review'
    rejection_reason: Optional[str] = None
    ambiguity_reason: Optional[str] = None
    source_provenance: str = "statement_import"
    raw_row_data: Dict[str, str] = field(default_factory=dict)
    lifecycle_status: str = "settled"
    cash_type: str = "immediate_debit"  # 'immediate_debit', 'future_debit', 'settled_income', 'non_cash'
    external_id: Optional[str] = None


@dataclass
class DialectInfo:
    delimiter: str
    has_header: bool
    date_column: str
    desc_column: str
    amount_column: Optional[str]
    debit_column: Optional[str]
    credit_column: Optional[str]
    currency_column: Optional[str]
    category_column: Optional[str]
    balance_column: Optional[str]
    date_format: str
    sign_convention: str  # 'standard' (debit negative), 'inverted' (debit positive)
    encoding: str = "utf-8"


@dataclass
class ImportPreview:
    batch_id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    content_hash: str
    state: IngestionState
    total_rows: int
    accepted_rows: int
    ambiguous_rows: int
    rejected_rows: int
    duplicate_rows: int
    detected_dialect: Optional[Dict[str, Any]]
    category_distribution: Dict[str, int]
    sample_transactions: List[Dict[str, Any]]
    validation_errors: List[str] = field(default_factory=list)
    requires_user_review: bool = False
