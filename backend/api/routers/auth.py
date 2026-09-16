"""
backend/api/routers/auth.py

Authentication router providing registration, Argon2id login, token revocation logout, and user profile.
Includes brute-force protection, IP throttling, and audit event emission.
"""
from __future__ import annotations
from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.api.config import settings
from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas.auth import AuthUserResponse, LoginRequest, RegisterRequest, TokenResponse
from backend.auth.jwt import create_access_token, decode_access_token
from backend.auth.passwords import PasswordPolicyError, hash_password, verify_password
from backend.auth.rate_limiter import get_rate_limiter
from backend.database.models.user import User
from backend.database.repositories.audit_repository import AuditRepository
from backend.database.repositories.revoked_token_repository import RevokedTokenRepository
from backend.database.repositories.user_repository import UserRepository

logger = logging.getLogger("buyorwait.api.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _get_client_ip(request: Request) -> str:
    """Extracts client IP address defending against forwarded spoofing."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


@router.post(
    "/register",
    response_model=AuthUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user account",
)
def register_user(
    req: RegisterRequest,
    session: Session = Depends(get_db),
):
    """
    Registers a new tenant account with Argon2id password hashing.
    Validates password complexity policy and enforces unique email addresses.
    """
    user_repo = UserRepository(session)
    
    # 1. Check if email already exists
    existing = user_repo.get_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists.",
        )

    # 2. Validate and hash password with Argon2id
    try:
        pw_hash = hash_password(req.password)
    except PasswordPolicyError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    # 3. Create user
    user = user_repo.create(
        email=req.email,
        full_name=req.full_name or "",
        password_hash=pw_hash,
    )
    session.flush()

    # 4. Audit user registration
    AuditRepository(session, user.id).log(
        event_type="user_registered",
        structured_metadata={"email": user.email, "full_name": user.full_name},
    )
    session.commit()

    return AuthUserResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        created_at=user.created_at,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive JWT access token",
)
def login_user(
    req: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
):
    """
    Authenticates user credentials using constant-time Argon2id verification.
    Enforces IP-based rate limiting and brute-force temporary lockouts.
    """
    ip = _get_client_ip(request)
    limiter = get_rate_limiter()

    # 1. Check brute force throttling for this IP + Email
    is_throttled, retry_after = limiter.is_login_throttled(ip, req.email)
    if is_throttled:
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # 2. Check general auth rate limit
    rl = limiter.check(f"auth:{ip}", limit=settings.RATE_LIMIT_AUTH, window_seconds=60)
    if not rl.allowed:
        response.headers["Retry-After"] = str(rl.retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for authentication. Retry in {rl.retry_after} seconds.",
            headers={"Retry-After": str(rl.retry_after)},
        )

    user_repo = UserRepository(session)
    user = user_repo.get_by_email(req.email)

    # 3. Constant-time verification
    pw_match = False
    if user and user.password_hash:
        pw_match = verify_password(user.password_hash, req.password)

    if not user or not pw_match:
        failures = limiter.record_failed_login(ip, req.email)
        # Audit failed login if user exists
        if user:
            AuditRepository(session, user.id).log(
                event_type="login_failed",
                structured_metadata={"ip": ip, "consecutive_failures": failures},
            )
            session.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is suspended (status: {user.status}). Contact support.",
        )

    # 4. Clear brute-force counter on success
    limiter.clear_failed_login(ip, req.email)

    # 5. Generate signed JWT token
    token = create_access_token(user_id=user.id, email=user.email)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # 6. Audit successful login
    AuditRepository(session, user.id).log(
        event_type="login_success",
        structured_metadata={"ip": ip},
    )
    session.commit()

    return TokenResponse(
        access_token=token,
        token_type="Bearer",
        expires_in=expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Revoke current access token",
)
def logout_user(
    current_user: User = Depends(get_current_user),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    session: Session = Depends(get_db),
):
    """
    Invalidates current session by storing token's unique jti in RevokedTokens.
    """
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token.")

    token = authorization.strip().split()[-1]
    try:
        payload = decode_access_token(token)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    jti = payload.get("jti")
    exp_epoch = payload.get("exp")
    if not jti or not exp_epoch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed token claims.")

    exp_dt = datetime.fromtimestamp(exp_epoch, tz=timezone.utc)
    rev_repo = RevokedTokenRepository(session)
    
    rev_repo.revoke(jti=jti, user_id=current_user.id, expires_at=exp_dt)
    AuditRepository(session, current_user.id).log(
        event_type="logout",
        structured_metadata={"jti": jti},
    )
    session.commit()

    return {"detail": "Successfully logged out. Token has been revoked."}


@router.get(
    "/me",
    response_model=AuthUserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get authenticated user identity",
)
def get_me(current_user: User = Depends(get_current_user)):
    """Returns current tenant profile without revealing password hash."""
    return AuthUserResponse(
        user_id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        status=current_user.status,
        created_at=current_user.created_at,
    )
