"""
backend/api/routers/imports.py
"""
from typing import Dict, List, Optional, Tuple
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from backend.api.dependencies import get_current_user, get_db, get_ingestion_service
from backend.api.schemas.import_statement import (
    ImportPreviewResponse,
    ImportUploadResponse,
    ImportVerifyRequest,
    ImportVerifyResponse,
)
from backend.database.models.user import User
from backend.database.repositories.import_batch_repository import ImportBatchRepository
from backend.ingestion.models import ImportPreview, NormalizedTransaction
from backend.ingestion.security import (
    FileOversizedError,
    IngestionSecurityError,
    InvalidFileTypeError,
    MaliciousContentError,
)
from backend.ingestion.service import DuplicateFileError, IngestionService

router = APIRouter(prefix="/imports", tags=["Statement Imports"])

# In-memory session preview staging cache: batch_id -> (ImportPreview, List[NormalizedTransaction])
_STAGED_IMPORTS: Dict[uuid.UUID, Tuple[ImportPreview, List[NormalizedTransaction]]] = {}


@router.post("", response_model=ImportUploadResponse, status_code=status.HTTP_201_CREATED, summary="Upload financial statement")
async def upload_statement(
    file: UploadFile = File(..., description="CSV statement file"),
    account_id: Optional[uuid.UUID] = Form(None, description="Target financial account ID"),
    sign_convention: str = Form("standard", description="'standard' or 'inverted'"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    service: IngestionService = Depends(get_ingestion_service),
) -> ImportUploadResponse:
    """
    Stages an uploaded financial statement: sanitizes, quarantines, parses,
    categorizes, and generates an uncommitted verification preview.
    """
    content = await file.read()

    preview, normalized_txns = service.stage_and_preview_statement(
        session=session,
        user_id=current_user.id,
        filename=file.filename or "statement.csv",
        content=content,
        account_id=account_id,
        sign_convention=sign_convention,
    )

    # Cache preview & normalized rows in memory for subsequent verification
    _STAGED_IMPORTS[preview.batch_id] = (preview, normalized_txns)

    return ImportUploadResponse(
        batch_id=str(preview.batch_id),
        filename=preview.filename,
        content_hash=preview.content_hash,
        status=preview.state.value,
        total_rows=preview.total_rows,
        accepted_rows=preview.accepted_rows,
        ambiguous_rows=preview.ambiguous_rows,
        duplicate_rows=preview.duplicate_rows,
        requires_user_review=preview.requires_user_review,
    )


@router.get("/{import_id}", summary="Get import batch details")
def get_import_batch(
    import_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Returns import batch metadata isolated to the authenticated tenant."""
    repo = ImportBatchRepository(session, current_user.id)
    batch = repo.get_by_id(import_id)
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")
    return {
        "id": str(batch.id),
        "filename": batch.filename,
        "content_hash": batch.content_hash,
        "upload_status": batch.upload_status,
        "parsing_status": batch.parsing_status,
        "verification_status": batch.verification_status,
        "total_rows": batch.total_rows,
        "imported_rows": batch.imported_rows,
        "created_at": batch.created_at.isoformat(),
    }


@router.get("/{import_id}/preview", response_model=ImportPreviewResponse, summary="Get statement verification preview")
def get_import_preview(
    import_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ImportPreviewResponse:
    """Returns preview of parsed, normalized, and categorized transactions awaiting user confirmation."""
    repo = ImportBatchRepository(session, current_user.id)
    batch = repo.get_by_id(import_id)
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")

    cached = _STAGED_IMPORTS.get(import_id)
    if cached:
        preview, _ = cached
        return ImportPreviewResponse(
            batch_id=str(preview.batch_id),
            filename=preview.filename,
            state=preview.state.value,
            total_rows=preview.total_rows,
            accepted_rows=preview.accepted_rows,
            ambiguous_rows=preview.ambiguous_rows,
            rejected_rows=preview.rejected_rows,
            duplicate_rows=preview.duplicate_rows,
            detected_dialect=preview.detected_dialect,
            category_distribution=preview.category_distribution,
            sample_transactions=preview.sample_transactions,
            validation_errors=preview.validation_errors,
            requires_user_review=preview.requires_user_review,
        )

    # Fallback to batch metadata if cache was evicted
    return ImportPreviewResponse(
        batch_id=str(batch.id),
        filename=batch.filename,
        state=batch.upload_status,
        total_rows=batch.total_rows,
        accepted_rows=batch.imported_rows or batch.total_rows,
        ambiguous_rows=0,
        rejected_rows=0,
        duplicate_rows=0,
        detected_dialect={},
        category_distribution={},
        sample_transactions=[],
        validation_errors=[],
        requires_user_review=False,
    )


@router.post("/{import_id}/verify", response_model=ImportVerifyResponse, summary="Verify and commit staged statement")
def verify_and_commit_import(
    import_id: uuid.UUID,
    body: ImportVerifyRequest = ImportVerifyRequest(),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    service: IngestionService = Depends(get_ingestion_service),
) -> ImportVerifyResponse:
    """Explicitly confirms and commits verified transactions into the permanent financial ledger."""
    repo = ImportBatchRepository(session, current_user.id)
    batch = repo.get_by_id(import_id)
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found.")

    cached = _STAGED_IMPORTS.get(import_id)
    if not cached:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Staged transaction data expired or already committed.",
        )

    _, normalized_txns = cached
    committed_count = service.commit_statement_batch(
        session=session,
        user_id=current_user.id,
        batch_id=import_id,
        normalized_transactions=normalized_txns,
        override_ambiguous=body.override_ambiguous,
    )

    # Remove from staging cache
    _STAGED_IMPORTS.pop(import_id, None)

    return ImportVerifyResponse(
        batch_id=str(import_id),
        status="committed",
        committed_rows=committed_count,
    )
