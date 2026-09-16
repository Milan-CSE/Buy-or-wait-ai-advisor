"""
backend/api/schemas/import_statement.py
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ImportUploadResponse(BaseModel):
    batch_id: str
    filename: str
    content_hash: str
    status: str
    total_rows: int
    accepted_rows: int
    ambiguous_rows: int
    duplicate_rows: int
    requires_user_review: bool


class ImportPreviewResponse(BaseModel):
    batch_id: str
    filename: str
    state: str
    total_rows: int
    accepted_rows: int
    ambiguous_rows: int
    rejected_rows: int
    duplicate_rows: int
    detected_dialect: Dict[str, Any]
    category_distribution: Dict[str, int]
    sample_transactions: List[Dict[str, Any]]
    validation_errors: List[str]
    requires_user_review: bool


class ImportVerifyRequest(BaseModel):
    override_ambiguous: bool = Field(default=False, description="Whether to commit ambiguous rows.")


class ImportVerifyResponse(BaseModel):
    batch_id: str
    status: str
    committed_rows: int
