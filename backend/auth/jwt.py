"""
backend/auth/jwt.py

Cryptographically signed JWT access tokens with short TTL and explicit claims.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import uuid
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError as PyJWTError

from backend.api.config import settings


class TokenExpiredError(Exception):
    """Raised when access token has expired."""
    pass


class InvalidTokenError(Exception):
    """Raised when token signature or claims are invalid."""
    pass


class TokenRevokedError(Exception):
    """Raised when token jti has been revoked."""
    pass


def create_access_token(
    user_id: uuid.UUID,
    email: str,
    expires_delta: Optional[timedelta] = None,
    custom_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generates a cryptographically signed HMAC-SHA256 JWT access token.
    Claims include:
    - sub: user UUID string
    - email: user email
    - jti: unique JWT identifier for revocation tracking
    - type: 'access'
    - iss: configured issuer ('buyorwait')
    - aud: configured audience ('buyorwait_api')
    - iat: issued-at UTC timestamp
    - exp: expiration UTC timestamp
    """
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "email": email.strip().lower(),
        "jti": str(uuid.uuid4()),
        "type": "access",
        "iss": settings.TOKEN_ISSUER,
        "aud": settings.TOKEN_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if custom_claims:
        payload.update(custom_claims)

    encoded = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and verifies a JWT access token.
    Validates:
    - HMAC signature using settings.JWT_SECRET_KEY
    - Expiration (exp)
    - Issuer (iss)
    - Audience (aud)
    - Token type ('access')
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.TOKEN_ISSUER,
            audience=settings.TOKEN_AUDIENCE,
            options={"require": ["sub", "exp", "iat", "jti", "type"]},
        )
    except ExpiredSignatureError as e:
        raise TokenExpiredError("Access token has expired.") from e
    except PyJWTError as e:
        raise InvalidTokenError(f"Invalid authentication token: {str(e)}") from e

    if payload.get("type") != "access":
        raise InvalidTokenError(f"Invalid token type: expected 'access', got '{payload.get('type')}'")

    return payload
