"""
backend/observability/redactor.py

Sensitive data redaction engine for structured logs and telemetry.
Protects credentials, tokens, account numbers, and raw financial payloads.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Union

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "jwt_secret_key",
    "secret",
    "raw_statement",
    "file_content",
    "account_number",
    "ssn",
    "credit_card",
}

# Regex patterns for tokens and card numbers
JWT_PATTERN = re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}")
BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+")
ACCOUNT_NUM_PATTERN = re.compile(r"\b\d{10,16}\b")


def redact_string(val: str) -> str:
    """Scrubs JWT tokens, Bearer headers, and long numeric sequences from text."""
    if not isinstance(val, str):
        return str(val)
    val = BEARER_PATTERN.sub("Bearer [REDACTED]", val)
    val = JWT_PATTERN.sub("[REDACTED]", val)
    val = ACCOUNT_NUM_PATTERN.sub("[REDACTED]", val)
    return val


def redact_data(data: Any) -> Any:
    """Recursively redacts dictionary, list, or primitive structures."""
    if isinstance(data, dict):
        clean = {}
        for k, v in data.items():
            key_lower = str(k).lower()
            if key_lower == "authorization" and isinstance(v, str) and v.lower().startswith("bearer "):
                clean[k] = "Bearer [REDACTED]"
            elif key_lower in SENSITIVE_KEYS:
                clean[k] = "[REDACTED]"
            else:
                clean[k] = redact_data(v)
        return clean
    elif isinstance(data, list):
        return [redact_data(item) for item in data]
    elif isinstance(data, str):
        return redact_string(data)
    else:
        return data
