"""
backend/api/schemas/common.py

Common Pydantic v2 models: RFC 7807 problem details and pagination.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class RFC7807Error(BaseModel):
    """RFC 7807 compliant problem details error response."""
    type: str = Field(default="about:blank", description="URI reference identifying problem type.")
    title: str = Field(..., description="Short human-readable summary of problem.")
    status: int = Field(..., description="HTTP status code.")
    detail: str = Field(..., description="Human-readable explanation specific to this occurrence.")
    instance: Optional[str] = Field(default=None, description="URI reference identifying specific occurrence.")
    code: str = Field(default="ERROR", description="Stable machine-readable error code.")
    invalid_params: Optional[List[Dict[str, Any]]] = Field(default=None, description="Detailed parameter errors if validation failed.")
    error: Optional[Dict[str, Any]] = Field(default=None, description="Nested domain error payload (e.g. DATA_INSUFFICIENT).")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standardized page-based pagination wrapper."""
    items: List[T] = Field(..., description="Current page records.")
    total: int = Field(..., description="Total available records matching query.")
    page: int = Field(..., ge=1, description="Current 1-indexed page number.")
    page_size: int = Field(..., ge=1, le=100, description="Records per page.")
    total_pages: int = Field(..., ge=0, description="Total available pages.")
