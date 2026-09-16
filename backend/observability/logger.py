"""
backend/observability/logger.py

Structured JSON log formatter with correlation ID, tenant masking, and safe redaction.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from backend.observability.redactor import redact_data


class JSONLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include standard request context if present
        for field in [
            "request_id",
            "correlation_id",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "user_id",
            "user_ref",
            "operation",
            "decision_id",
            "verdict",
            "risk_tier",
            "engine_version",
            "calibration_version",
            "error_code",
        ]:
            if hasattr(record, field):
                log_obj[field] = getattr(record, field)

        # Merge extra attributes safely
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_obj.update(record.extra)

        # Exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Redact any accidental sensitive content
        sanitized = redact_data(log_obj)
        return json.dumps(sanitized)


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configures root logger with JSONLogFormatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONLogFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
