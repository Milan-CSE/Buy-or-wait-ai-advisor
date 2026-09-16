"""
backend/ingestion/security.py

Security controls, file validation, path traversal defense, and quarantine storage.
"""
from __future__ import annotations
import hashlib
import os
import re
import uuid
from typing import Tuple


MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit
ALLOWED_EXTENSIONS = {".csv", ".txt", ".tsv"}

# Magic bytes for binary / executable / archive formats that must be rejected
DISALLOWED_MAGIC_BYTES = [
    (b"MZ", "Windows PE executable / DLL"),
    (b"\x7fELF", "Linux ELF executable"),
    (b"\xca\xfe\xba\xbe", "Java class / Mach-O binary"),
    (b"\xfe\xed\xfa\xce", "Mach-O binary"),
    (b"\xfe\xed\xfa\xcf", "Mach-O binary"),
    (b"PK\x03\x04", "ZIP / Archive file"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"\x1f\x8b\x08", "GZIP compressed archive"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (b"%PDF-", "PDF document"),
]


class IngestionSecurityError(Exception):
    """Raised when file validation or security checks fail."""
    pass


class FileOversizedError(IngestionSecurityError):
    """Raised when uploaded file exceeds maximum allowed size."""
    pass


class InvalidFileTypeError(IngestionSecurityError):
    """Raised when file extension or MIME content is disallowed."""
    pass


class MaliciousContentError(IngestionSecurityError):
    """Raised when binary executables, null bytes, or malicious payloads are detected."""
    pass


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes user-provided filename to prevent path traversal and shell injection.
    Strips directory separators, null bytes, and unsafe characters.
    """
    if not filename or not isinstance(filename, str):
        return f"statement_{uuid.uuid4().hex[:8]}.csv"

    # Remove null bytes
    clean = filename.replace("\0", "")

    # Take only basename to prevent path traversal
    clean = os.path.basename(clean.replace("\\", "/"))

    # Strip dangerous characters, keeping alphanumeric, dots, underscores, dashes
    clean = re.sub(r"[^a-zA-Z0-9._-]", "_", clean)

    # Prevent empty or hidden files (e.g. '.bashrc', '...')
    clean = clean.lstrip(".")
    if not clean:
        clean = f"statement_{uuid.uuid4().hex[:8]}.csv"

    return clean


def compute_sha256(content: bytes) -> str:
    """Computes SHA-256 digest of content bytes."""
    return hashlib.sha256(content).hexdigest()


def validate_file_content(filename: str, content: bytes) -> None:
    """
    Validates uploaded file size, extension, and binary signatures.
    Raises IngestionSecurityError if invalid.
    """
    # 1. Size check
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise FileOversizedError(
            f"File size {len(content)} bytes exceeds maximum limit of {MAX_FILE_SIZE_BYTES} bytes (10MB)."
        )

    if len(content) == 0:
        raise IngestionSecurityError("Uploaded file is empty (0 bytes).")

    # 2. Extension check
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidFileTypeError(
            f"Disallowed file extension '{ext}'. Allowed extensions are: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 3. Binary magic bytes check
    for magic, desc in DISALLOWED_MAGIC_BYTES:
        if content.startswith(magic):
            raise MaliciousContentError(
                f"File content rejected: detected binary/executable signature ({desc})."
            )

    # 4. Null byte check in text statement
    if b"\x00" in content:
        raise MaliciousContentError("File content rejected: contains binary null bytes (\\x00).")


class QuarantineStorage:
    """
    Local secure storage abstraction for quarantining raw statement files.
    Files are stored with random UUID filenames inside a private quarantine directory.
    """
    def __init__(self, base_dir: str = "backend/ingestion/quarantine"):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    def store_file(self, user_id: uuid.UUID, content: bytes) -> str:
        """
        Stores file content in quarantine and returns the absolute path.
        """
        user_quarantine_dir = os.path.join(self.base_dir, str(user_id))
        os.makedirs(user_quarantine_dir, exist_ok=True)

        quarantine_filename = f"{uuid.uuid4().hex}.raw"
        dest_path = os.path.join(user_quarantine_dir, quarantine_filename)

        # Ensure no path traversal outside base_dir
        dest_path = os.path.abspath(dest_path)
        if not dest_path.startswith(self.base_dir):
            raise IngestionSecurityError("Path traversal detected during quarantine storage.")

        with open(dest_path, "wb") as f:
            f.write(content)

        return dest_path

    def read_file(self, quarantine_path: str) -> bytes:
        """Reads file from quarantine with path verification."""
        abs_path = os.path.abspath(quarantine_path)
        if not abs_path.startswith(self.base_dir) or not os.path.exists(abs_path):
            raise IngestionSecurityError("Invalid or missing quarantine file path.")
        with open(abs_path, "rb") as f:
            return f.read()

    def remove_file(self, quarantine_path: str) -> None:
        """Safely removes file from quarantine."""
        abs_path = os.path.abspath(quarantine_path)
        if abs_path.startswith(self.base_dir) and os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                pass
