"""
backend/database/repositories/import_batch_repository.py

Tenant-isolated repository for ImportBatch entities.
"""
from __future__ import annotations
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.import_batch import ImportBatch
from backend.database.repositories.base import TenantScopedRepository


class ImportBatchRepository(TenantScopedRepository[ImportBatch]):
    def __init__(self, session: Session, user_id: uuid.UUID):
        super().__init__(session, user_id, ImportBatch)

    def get_by_content_hash(self, content_hash: str) -> Optional[ImportBatch]:
        stmt = select(ImportBatch).where(
            ImportBatch.user_id == self.user_id,
            ImportBatch.content_hash == content_hash,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        filename: str,
        content_hash: str,
        source_type: str = "csv_statement",
    ) -> ImportBatch:
        batch = ImportBatch(
            user_id=self.user_id,
            filename=filename,
            content_hash=content_hash,
            source_type=source_type,
            upload_status="pending",
        )
        self.session.add(batch)
        return batch
