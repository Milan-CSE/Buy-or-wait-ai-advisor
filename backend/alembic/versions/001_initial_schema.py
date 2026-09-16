"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-15 11:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # 2. financial_profiles table
    op.create_table(
        "financial_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("home_currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("current_available_balance", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("minimum_balance_to_keep", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("reserve_policy", sa.String(length=64), nullable=False, server_default="strict_minimum"),
        sa.Column("protected_categories", sa.JSON(), nullable=False),
        sa.Column("reducible_categories", sa.JSON(), nullable=False),
        sa.Column("stoppable_categories", sa.JSON(), nullable=False),
        sa.Column("payment_methods", sa.JSON(), nullable=False),
        sa.Column("max_installment_months", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_financial_profiles_user_id", "financial_profiles", ["user_id"])

    # 3. financial_accounts table
    op.create_table(
        "financial_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("institution_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("account_mask", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("current_balance", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_financial_accounts_user_id", "financial_accounts", ["user_id"])

    # 4. import_batches table
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False, server_default="csv_statement"),
        sa.Column("upload_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("parsing_status", sa.String(length=32), nullable=False, server_default="parsed"),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="verified"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_user_id", "import_batches", ["user_id"])
    op.create_index("ix_import_batches_content_hash", "import_batches", ["content_hash"])

    # 5. transactions table
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("import_batch_id", sa.Uuid(), nullable=True),
        sa.Column("external_transaction_id", sa.String(length=128), nullable=True),
        sa.Column("dedup_hash", sa.String(length=64), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("amount_home", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("normalized_description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("original_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="settled"),
        sa.Column("cash_type", sa.String(length=32), nullable=False, server_default="immediate_debit"),
        sa.Column("flexibility", sa.String(length=32), nullable=False, server_default="fixed"),
        sa.Column("minimum_allowed_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("linked_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("source_provenance", sa.String(length=64), nullable=False, server_default="statement_import"),
        sa.Column("confidence_state", sa.String(length=32), nullable=False, server_default="verified"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["financial_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_transaction_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_transaction_date", "transactions", ["transaction_date"])
    op.create_index("ix_transactions_category", "transactions", ["category"])
    op.create_index("ix_user_tx_date", "transactions", ["user_id", "transaction_date"])
    op.create_index("ix_user_dedup", "transactions", ["user_id", "dedup_hash"])

    # 6. purchase_requests table
    op.create_table(
        "purchase_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("request_date", sa.Date(), nullable=False),
        sa.Column("desired_completion_date", sa.Date(), nullable=False),
        sa.Column("allows_partial_payment", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("item_description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("merchant_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payment_options_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_requests_user_id", "purchase_requests", ["user_id"])

    # 7. decisions table
    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_request_id", sa.Uuid(), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False, server_default="1.0.0"),
        sa.Column("calibration_version", sa.String(length=64), nullable=False, server_default="v3_empirical_q90_20260914"),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("amount_safe_to_pay", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("affordability_status", sa.String(length=32), nullable=False),
        sa.Column("recommended_payment_method", sa.String(length=32), nullable=False),
        sa.Column("payment_plan", sa.Text(), nullable=False, server_default="none"),
        sa.Column("earliest_date_for_full_payment", sa.Date(), nullable=True),
        sa.Column("spending_changes_needed", sa.Text(), nullable=False, server_default="none"),
        sa.Column("decision_explanation", sa.Text(), nullable=False),
        sa.Column("risk_tier", sa.String(length=32), nullable=False, server_default="LOW_RISK"),
        sa.Column("safe_amount_p50", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("safe_amount_p90", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("minimum_balance_p50", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("minimum_balance_p90", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("headroom_p50", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("headroom_p90", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("risk_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("stress_summary", sa.String(length=255), nullable=False, server_default="none"),
        sa.Column("p90_breach_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("audit_metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_request_id"], ["purchase_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_request_id"),
    )
    op.create_index("ix_decisions_user_id", "decisions", ["user_id"])

    # 8. audit_events table
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("structured_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("decisions")
    op.drop_table("purchase_requests")
    op.drop_table("transactions")
    op.drop_table("import_batches")
    op.drop_table("financial_accounts")
    op.drop_table("financial_profiles")
    op.drop_table("users")
