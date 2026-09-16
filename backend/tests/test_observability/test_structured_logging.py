"""
backend/tests/test_observability/test_structured_logging.py

Tests for JSONLogFormatter, correlation IDs, and sensitive data redaction.
"""
import json
import logging
from backend.observability.logger import JSONLogFormatter
from backend.observability.redactor import redact_data, redact_string


class TestStructuredLogging:
    def test_json_formatting_and_standard_fields(self):
        formatter = JSONLogFormatter()
        record = logging.LogRecord(
            name="buyorwait.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Transaction evaluated successfully",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-abc-123"
        record.user_id = "usr-456"

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "buyorwait.test"
        assert parsed["message"] == "Transaction evaluated successfully"
        assert parsed["request_id"] == "req-abc-123"
        assert parsed["user_id"] == "usr-456"
        assert "timestamp" in parsed

    def test_sensitive_field_redaction_in_dict(self):
        raw = {
            "user_id": "usr-1",
            "password": "superSecret123!",
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz",
            "account_number": "98765432101234",
            "safe_amount": "150.00",
            "headers": {
                "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"
            }
        }
        redacted = redact_data(raw)
        assert redacted["password"] == "[REDACTED]"
        assert redacted["access_token"] == "[REDACTED]"
        assert redacted["account_number"] == "[REDACTED]"
        assert redacted["headers"]["authorization"] == "Bearer [REDACTED]"
        assert redacted["safe_amount"] == "150.00"
        assert redacted["user_id"] == "usr-1"

    def test_sensitive_pattern_redaction_in_string(self):
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdef"
        raw_msg = f"Failed authorization with header Bearer {token}"
        redacted = redact_string(raw_msg)
        assert token not in redacted
        assert "Bearer [REDACTED]" in redacted

    def test_account_number_redaction_in_prose(self):
        prose = "Transferred funds from account 123456789012 to checking"
        redacted = redact_string(prose)
        assert "123456789012" not in redacted
        assert "[REDACTED]" in redacted
