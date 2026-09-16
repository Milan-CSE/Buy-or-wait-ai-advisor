"""
backend/api/schemas/health.py
"""
from datetime import datetime
from typing import Dict, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(default="healthy", description="Service health indicator.")
    api_version: str = Field(default="1.0.0", description="API version.")
    engine_version: str = Field(default="1.0.0", description="Core decision engine version.")
    risk_calibration_version: str = Field(default="v3_empirical_q90_20260914", description="Risk calibration version.")
    timestamp: datetime = Field(..., description="Current server time.")


class LivenessResponse(BaseModel):
    status: str = Field(default="alive", description="Process liveness indicator.")
    timestamp: datetime = Field(..., description="Current server time.")


class ReadinessResponse(BaseModel):
    status: str = Field(description="Readiness status ('ready' or 'unready').")
    database: str = Field(description="Database connectivity status ('connected' or 'disconnected').")
    dependencies: Dict[str, str] = Field(default_factory=dict, description="Dependency status map.")
    timestamp: datetime = Field(..., description="Current server time.")
