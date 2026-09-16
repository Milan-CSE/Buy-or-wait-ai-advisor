"""
backend/api/config.py

Hardened production configuration for Buy or Wait? API.
Enforces environment profiles (development, testing, production) and secret validation.
"""
from __future__ import annotations
import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Buy or Wait? Decision API"
    API_VERSION: str = "1.0.0"
    ENGINE_VERSION: str = "1.0.0"
    CALIBRATION_VERSION: str = "v3_empirical_q90_20260914"

    # Security & JWT Configuration
    JWT_SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY",
        "insecure-dev-signing-key-minimum-32-chars-change-in-prod-immediately!",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    TOKEN_ISSUER: str = "buyorwait"
    TOKEN_AUDIENCE: str = "buyorwait_api"

    # Rate Limiting Configuration (requests per 60-second window)
    RATE_LIMIT_AUTH: int = int(os.getenv("RATE_LIMIT_AUTH", "5"))
    RATE_LIMIT_UPLOAD: int = int(os.getenv("RATE_LIMIT_UPLOAD", "10"))
    RATE_LIMIT_EVALUATE: int = int(os.getenv("RATE_LIMIT_EVALUATE", "30"))
    RATE_LIMIT_GENERAL: int = int(os.getenv("RATE_LIMIT_GENERAL", "120"))

    # CORS configuration - strict by default, never allow wildcard with credentials
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///buyorwait_dev.db")

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", extra="ignore")

    def validate_production_security(self) -> None:
        """Enforces security invariants in production mode."""
        if self.ENVIRONMENT == "production":
            if len(self.JWT_SECRET_KEY) < 32 or "insecure" in self.JWT_SECRET_KEY.lower():
                raise RuntimeError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Production environment requires a strong, "
                    "randomly generated JWT_SECRET_KEY with at least 32 characters."
                )
            if "*" in self.CORS_ORIGINS:
                raise RuntimeError(
                    "CRITICAL SECURITY CONFIGURATION ERROR: Wildcard CORS origin ('*') is prohibited in production."
                )


settings = Settings()
settings.validate_production_security()
