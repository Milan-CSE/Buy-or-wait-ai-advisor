"""
backend/api/schemas/auth.py

Pydantic v2 schemas for authentication, registration, token responses, and credential management.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Strong password with letters, numbers, and symbols")
    full_name: Optional[str] = Field(default="", max_length=255)

    model_config = ConfigDict(extra="forbid")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., description="User password")

    model_config = ConfigDict(extra="forbid")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(..., description="Token validity duration in seconds")

    model_config = ConfigDict(extra="forbid")


class AuthUserResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    status: str
    created_at: datetime

    model_config = ConfigDict(extra="forbid", from_attributes=True)
