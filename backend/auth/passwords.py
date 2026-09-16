"""
backend/auth/passwords.py

Argon2id password hashing, constant-time verification, and password complexity policy.
"""
from __future__ import annotations
import re
from typing import Optional
import argon2
from argon2.exceptions import VerifyMismatchError, InvalidHashError

# PasswordHasher configured with recommended OWASP Argon2id parameters
_hasher = argon2.PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=1,
    hash_len=32,
    type=argon2.Type.ID,
)


class PasswordPolicyError(ValueError):
    """Raised when a candidate password violates complexity requirements."""
    pass


def validate_password_strength(password: str) -> None:
    """
    Enforces strong password policy:
    - Minimum 8 characters
    - At least one lowercase letter
    - At least one uppercase letter
    - At least one numeric digit
    - At least one special symbol
    """
    if len(password) < 8:
        raise PasswordPolicyError("Password must be at least 8 characters long.")
    if not re.search(r"[a-z]", password):
        raise PasswordPolicyError("Password must contain at least one lowercase letter.")
    if not re.search(r"[A-Z]", password):
        raise PasswordPolicyError("Password must contain at least one uppercase letter.")
    if not re.search(r"[0-9]", password):
        raise PasswordPolicyError("Password must contain at least one numeric digit.")
    special_chars = set('!@#$%^&*(),.?":{}|<>-=_+[]/;`~')
    if not any(c in special_chars for c in password):
        raise PasswordPolicyError("Password must contain at least one special character.")


def hash_password(password: str) -> str:
    """
    Generates a secure Argon2id hash with per-hash random salt.
    Never stores or logs the plaintext password.
    """
    validate_password_strength(password)
    return _hasher.hash(password)


def verify_password(password_hash: Optional[str], password: str) -> bool:
    """
    Verifies candidate plaintext against an Argon2id hash in constant time.
    Safely handles None, corrupted hashes, or mismatches without leaking timing info.
    """
    if not password_hash or not password:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False
