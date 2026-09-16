"""
backend/ingestion/service.py

Ingestion service orchestrating the multi-stage state machine:
Upload -> Validate -> Parse -> Normalize -> Deduplicate -> Preview -> Commit.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database.models.import_batch import ImportBatch
from backend.database.models.transaction import Transaction
from backend.database.models.account import FinancialAccount
from backend.database.models.audit import AuditEvent
from backend.database.repositories.base import TenantAccessError
from backend.ingestion.categorizer import RuleBasedCategorizer
from backend.ingestion.deduplicator import StatementDeduplicator
from backend.ingestion.dialect import DialectDetector
from backend.ingestion.models import (
    DialectInfo,
    ImportPreview,
    IngestionState,
    NormalizedTransaction,
    ParsedRow,
    VerificationStatus,
)
from backend.ingestion.normalizer import TransactionNormalizer
from backend.ingestion.parsers.csv_parser import CSVStatementParser
from backend.ingestion.security import (
    IngestionSecurityError,
    QuarantineStorage,
    compute_sha256,
    sanitize_filename,
    validate_file_content,
)
from backend.ingestion.transfers import InternalTransferDetector


class DuplicateFileError(IngestionSecurityError):
    """Raised when an identical file has already been ingested."""
    pass


class IngestionService:
    """
    Main entry point for financial statement ingestion.
    Enforces user isolation, security boundaries, and the verification checkpoint.
    """

    def __init__(self, quarantine_storage: Optional[QuarantineStorage] = None):
        self.storage = quarantine_storage or QuarantineStorage()
        self.parser = CSVStatementParser()

    def stage_and_preview_statement(
        self,
        session: Session,
        user_id: uuid.UUID,
        filename: str,
        content: bytes,
        account_id: Optional[uuid.UUID] = None,
        sign_convention: str = "standard",
    ) -> Tuple[ImportPreview, List[NormalizedTransaction]]:
        """
        Executes ingestion stages up to Verification Preview:
        1. Sanitize & validate security
        2. Detect duplicate files
        3. Quarantine raw file
        4. Detect dialect & parse rows
        5. Normalize, categorize, detect transfers, and deduplicate rows
        6. Produce ImportPreview without committing to financial ledger.
        """
        # 1. Filename sanitization
        clean_name = sanitize_filename(filename)

        # 2. File validation & Security checks
        validate_file_content(clean_name, content)

        # 3. Content hash & Duplicate file check
        file_hash = compute_sha256(content)
        existing_batch = StatementDeduplicator.is_duplicate_file(session, user_id, file_hash)
        if existing_batch:
            raise DuplicateFileError(
                f"Duplicate statement file detected (SHA-256: {file_hash}). "
                f"Already processed in batch {existing_batch.id} on {existing_batch.created_at}."
            )

        # 4. Quarantine raw bytes
        quarantine_path = self.storage.store_file(user_id, content)

        # 5. Create initial ImportBatch entity
        batch = ImportBatch(
            user_id=user_id,
            filename=clean_name,
            content_hash=file_hash,
            source_type="csv_statement",
            upload_status=IngestionState.VALIDATING.value,
            parsing_status="pending",
            verification_status="unverified",
            total_rows=0,
            imported_rows=0,
        )
        session.add(batch)
        session.flush()

        # 6. Parse CSV content
        dialect, parsed_rows, parse_errors = self.parser.parse(content)
        if sign_convention != "standard":
            dialect.sign_convention = sign_convention

        batch.total_rows = len(parsed_rows)
        batch.parsing_status = "parsed" if not parse_errors else "parsed_with_errors"

        # Lookup user account names for internal transfer detection
        user_acc_rows = session.execute(
            select(FinancialAccount.institution_name, FinancialAccount.account_type, FinancialAccount.account_mask)
            .where(FinancialAccount.user_id == user_id)
        ).all()
        user_accs = [
            str(val) for row in user_acc_rows for val in row if val
        ]

        # 7. Normalize, Categorize, Deduplicate
        normalized_txns: List[NormalizedTransaction] = []
        seen_in_batch_hashes: Set[str] = set()

        accepted_count = 0
        ambiguous_count = 0
        rejected_count = 0
        duplicate_count = 0
        category_counts: Counter[str] = Counter()

        for row in parsed_rows:
            # 7a. Date parsing
            parsed_date, date_err = TransactionNormalizer.parse_date(row.date_str, dialect.date_format)
            if date_err or not parsed_date:
                norm = NormalizedTransaction(
                    user_id=user_id,
                    account_id=account_id,
                    import_batch_id=batch.id,
                    line_number=row.line_number,
                    transaction_date=date.today(),
                    amount=Decimal("0.0000"),
                    direction="debit",
                    currency=row.currency_str or "USD",
                    normalized_description=TransactionNormalizer.normalize_description(row.description_str),
                    original_description=row.description_str or "",
                    category="other",
                    category_reason="unparsed",
                    is_internal_transfer=False,
                    dedup_hash="",
                    verification_status=VerificationStatus.REJECTED,
                    confidence_state="needs_review",
                    rejection_reason=date_err,
                    raw_row_data=row.raw_fields,
                )
                normalized_txns.append(norm)
                rejected_count += 1
                continue

            # 7b. Amount and Direction
            amount, direction, amt_status, amt_reason = TransactionNormalizer.resolve_amount_and_direction(row, dialect)
            if amt_status == VerificationStatus.AMBIGUOUS:
                norm = NormalizedTransaction(
                    user_id=user_id,
                    account_id=account_id,
                    import_batch_id=batch.id,
                    line_number=row.line_number,
                    transaction_date=parsed_date,
                    amount=amount if amount is not None else Decimal("0.0000"),
                    direction=direction,
                    currency=row.currency_str or "USD",
                    normalized_description=TransactionNormalizer.normalize_description(row.description_str),
                    original_description=row.description_str or "",
                    category="other",
                    category_reason="ambiguous_amount",
                    is_internal_transfer=False,
                    dedup_hash="",
                    verification_status=VerificationStatus.AMBIGUOUS,
                    confidence_state="needs_review",
                    ambiguity_reason=amt_reason,
                    raw_row_data=row.raw_fields,
                )
                normalized_txns.append(norm)
                ambiguous_count += 1
                continue

            if amt_status == VerificationStatus.REJECTED or amount is None:
                norm = NormalizedTransaction(
                    user_id=user_id,
                    account_id=account_id,
                    import_batch_id=batch.id,
                    line_number=row.line_number,
                    transaction_date=parsed_date,
                    amount=Decimal("0.0000"),
                    direction="debit",
                    currency=row.currency_str or "USD",
                    normalized_description=TransactionNormalizer.normalize_description(row.description_str),
                    original_description=row.description_str or "",
                    category="other",
                    category_reason="unparsed",
                    is_internal_transfer=False,
                    dedup_hash="",
                    verification_status=VerificationStatus.REJECTED,
                    confidence_state="needs_review",
                    rejection_reason=amt_reason,
                    raw_row_data=row.raw_fields,
                )
                normalized_txns.append(norm)
                rejected_count += 1
                continue

            # 7c. Description and Categorization
            norm_desc = TransactionNormalizer.normalize_description(row.description_str)
            orig_desc = row.description_str or ""
            is_internal = InternalTransferDetector.is_internal_transfer(norm_desc, user_accs)

            if is_internal:
                category = "transfer"
                cat_reason = "internal_transfer_rule"
                cash_type = "non_cash"
            else:
                category, cat_reason = RuleBasedCategorizer.categorize(norm_desc, row.category_str)
                cash_type = "immediate_debit" if direction == "debit" else "settled_income"

            # 7d. Deduplication
            tx_hash = StatementDeduplicator.compute_transaction_hash(
                user_id=user_id,
                account_id=account_id,
                txn_date=parsed_date,
                amount=amount,
                normalized_description=norm_desc,
            )

            is_dup = (
                tx_hash in seen_in_batch_hashes
                or StatementDeduplicator.is_duplicate_transaction(session, user_id, tx_hash)
            )

            if is_dup:
                status = VerificationStatus.DUPLICATE
                duplicate_count += 1
            else:
                seen_in_batch_hashes.add(tx_hash)
                status = VerificationStatus.VERIFIED
                accepted_count += 1
                category_counts[category] += 1

            norm_txn = NormalizedTransaction(
                user_id=user_id,
                account_id=account_id,
                import_batch_id=batch.id,
                line_number=row.line_number,
                transaction_date=parsed_date,
                amount=amount,
                direction=direction,
                currency=row.currency_str or "USD",
                normalized_description=norm_desc,
                original_description=orig_desc,
                category=category,
                category_reason=cat_reason,
                is_internal_transfer=is_internal,
                dedup_hash=tx_hash,
                verification_status=status,
                confidence_state="verified" if status == VerificationStatus.VERIFIED else "needs_review",
                raw_row_data=row.raw_fields,
                lifecycle_status="settled",
                cash_type=cash_type,
            )
            normalized_txns.append(norm_txn)

        # 8. Update Batch Status
        requires_review = (ambiguous_count > 0 or rejected_count > 0 or duplicate_count > 0)
        final_state = IngestionState.NEEDS_REVIEW if requires_review else IngestionState.VERIFIED

        batch.upload_status = final_state.value
        batch.verification_status = "unverified" if requires_review else "verified"
        session.commit()

        # Build preview payload
        sample_display = []
        for t in normalized_txns[:10]:
            sample_display.append({
                "line": t.line_number,
                "date": t.transaction_date.isoformat(),
                "amount": str(t.amount),
                "direction": t.direction,
                "description": t.normalized_description,
                "category": t.category,
                "status": t.verification_status.value,
                "is_transfer": t.is_internal_transfer,
                "reason": t.ambiguity_reason or t.rejection_reason or t.category_reason,
            })

        preview = ImportPreview(
            batch_id=batch.id,
            user_id=user_id,
            filename=clean_name,
            content_hash=file_hash,
            state=final_state,
            total_rows=len(parsed_rows),
            accepted_rows=accepted_count,
            ambiguous_rows=ambiguous_count,
            rejected_rows=rejected_count,
            duplicate_rows=duplicate_count,
            detected_dialect={
                "delimiter": dialect.delimiter,
                "date_column": dialect.date_column,
                "desc_column": dialect.desc_column,
                "amount_column": dialect.amount_column,
                "debit_column": dialect.debit_column,
                "credit_column": dialect.credit_column,
                "date_format": dialect.date_format,
                "encoding": dialect.encoding,
            },
            category_distribution=dict(category_counts),
            sample_transactions=sample_display,
            validation_errors=parse_errors,
            requires_user_review=requires_review,
        )

        return preview, normalized_txns

    def commit_statement_batch(
        self,
        session: Session,
        user_id: uuid.UUID,
        batch_id: uuid.UUID,
        normalized_transactions: List[NormalizedTransaction],
        override_ambiguous: bool = False,
    ) -> int:
        """
        Commits verified normalized transactions to the official financial ledger.
        Enforces tenant check and rejects unverified rows unless explicitly overridden.
        """
        batch = session.execute(
            select(ImportBatch).where(ImportBatch.id == batch_id)
        ).scalar_one_or_none()

        if not batch:
            raise ValueError(f"ImportBatch {batch_id} not found.")

        if batch.user_id != user_id:
            raise TenantAccessError("Cannot commit import batch belonging to another user.")

        if batch.upload_status == IngestionState.COMMITTED.value:
            raise ValueError(f"ImportBatch {batch_id} has already been committed.")

        # Filter transactions that can be committed
        to_commit: List[Transaction] = []
        for item in normalized_transactions:
            if item.import_batch_id != batch_id or item.user_id != user_id:
                continue

            if item.verification_status == VerificationStatus.VERIFIED:
                can_commit = True
            elif item.verification_status == VerificationStatus.AMBIGUOUS and override_ambiguous:
                can_commit = True
            else:
                can_commit = False

            if not can_commit:
                continue

            # Check once more for deduplication before insertion
            if StatementDeduplicator.is_duplicate_transaction(session, user_id, item.dedup_hash):
                continue

            tx = Transaction(
                user_id=user_id,
                account_id=item.account_id,
                import_batch_id=batch_id,
                external_transaction_id=item.external_id,
                dedup_hash=item.dedup_hash,
                transaction_date=item.transaction_date,
                amount=item.amount,
                currency=item.currency,
                amount_home=item.amount,  # Same currency assumption for statement home
                direction=item.direction,
                normalized_description=item.normalized_description,
                original_description=item.original_description,
                category=item.category,
                lifecycle_status=item.lifecycle_status,
                cash_type=item.cash_type,
                flexibility="fixed",
                source_provenance=item.source_provenance,
                confidence_state=item.confidence_state,
            )
            to_commit.append(tx)

        session.add_all(to_commit)

        # Update batch state
        batch.upload_status = IngestionState.COMMITTED.value
        batch.verification_status = "verified"
        batch.imported_rows = len(to_commit)

        # Emit audit event
        audit = AuditEvent(
            user_id=user_id,
            event_type="statement_batch_committed",
            actor_type="user",
            actor_id=str(user_id),
            structured_metadata={
                "batch_id": str(batch_id),
                "total_rows": batch.total_rows,
                "committed_rows": len(to_commit),
                "filename": batch.filename,
                "content_hash": batch.content_hash,
            },
        )
        session.add(audit)
        session.commit()

        return len(to_commit)
