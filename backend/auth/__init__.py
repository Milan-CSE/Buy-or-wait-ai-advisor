"""
backend/auth package

Security, Argon2id password hashing, JWT signed tokens, and rate limiting.
"""
from backend.auth.passwords import (
    hash_password,
    verify_password,
    validate_password_strength,
    PasswordPolicyError,
)
from backend.auth.jwt import (
    create_access_token,
    decode_access_token,
    TokenExpiredError,
    InvalidTokenError,
    TokenRevokedError,
)
from backend.auth.rate_limiter import (
    get_rate_limiter,
    RateLimiter,
)

__all__ = [
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "PasswordPolicyError",
    "create_access_token",
    "decode_access_token",
    "TokenExpiredError",
    "InvalidTokenError",
    "TokenRevokedError",
    "get_rate_limiter",
    "RateLimiter",
]
