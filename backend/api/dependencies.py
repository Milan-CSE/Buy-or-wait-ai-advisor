"""
backend/api/dependencies.py

FastAPI dependency providers for database session, JWT authentication, and services.
Enforces strict Bearer JWT token verification and token revocation checks.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import logging
from typing import Generator, Optional
import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.auth.jwt import (
    TokenExpiredError,
    TokenRevokedError,
    decode_access_token,
)
from backend.database.models.user import User
from backend.database.repositories.revoked_token_repository import RevokedTokenRepository
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import SessionFactory
from backend.ingestion.service import IngestionService
from backend.services.decision_service import DecisionService
from buyorwait_engine.currency.fx import FXEngine

logger = logging.getLogger("buyorwait.api")

# Cached FXEngine instance for API runtime
_GLOBAL_FX: Optional[FXEngine] = None


def get_fx_engine() -> FXEngine:
    global _GLOBAL_FX
    if _GLOBAL_FX is None:
        engine = FXEngine()
        # Seed standard development FX pairs if empty
        ref_dt = date(2026, 3, 1)
        engine.add_rate(ref_dt, "EUR", "USD", Decimal("1.1000"))
        engine.add_rate(ref_dt, "GBP", "USD", Decimal("1.2500"))
        engine.add_rate(ref_dt, "INR", "USD", Decimal("0.0120"))
        engine.add_rate(ref_dt, "ZAR", "USD", Decimal("0.0550"))
        engine.add_rate(ref_dt, "IDR", "USD", Decimal("0.000065"))
        _GLOBAL_FX = engine
    return _GLOBAL_FX


def get_db() -> Generator[Session, None, None]:
    """Yields a database session with transaction management."""
    session = SessionFactory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    session: Session = Depends(get_db),
) -> User:
    """
    Enforces authentication boundary using cryptographically signed JWT access tokens.
    Rejects missing, expired, revoked, or invalid tokens with RFC 7807 problem details.
    Zero client trust: No raw user IDs or development shortcuts are accepted.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Expected 'Authorization: Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]

    # 1. Decode and verify JWT signature and claims
    try:
        payload = decode_access_token(token)
    except TokenExpiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={'WWW-Authenticate': 'Bearer error="invalid_token", error_description="The token has expired"'},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    sub = payload.get("sub")
    if not jti or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token claims missing mandatory subject or identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Check token revocation blacklist
    rev_repo = RevokedTokenRepository(session)
    if rev_repo.is_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has been revoked.",
            headers={'WWW-Authenticate': 'Bearer error="invalid_token", error_description="Token revoked"'},
        )

    # 3. Resolve user identity from sub UUID
    try:
        user_uuid = uuid.UUID(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user identifier in token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(session)
    user = user_repo.get_by_id(user_uuid)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with token no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User account is not active (status: {user.status}).",
        )

    return user


def get_decision_service(
    session: Session = Depends(get_db),
    fx: FXEngine = Depends(get_fx_engine),
) -> DecisionService:
    return DecisionService(session=session, fx_engine=fx)


# Singleton IngestionService with in-memory preview staging
_GLOBAL_INGESTION_SERVICE: Optional[IngestionService] = None


def get_ingestion_service() -> IngestionService:
    global _GLOBAL_INGESTION_SERVICE
    if _GLOBAL_INGESTION_SERVICE is None:
        _GLOBAL_INGESTION_SERVICE = IngestionService()
    return _GLOBAL_INGESTION_SERVICE
