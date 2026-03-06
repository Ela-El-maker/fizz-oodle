"""Stage 5 analyst report contracts.

Revision ID: 0006_stage5_analyst_reports
Revises: 0005_stage4_sentiment_full
Create Date: 2026-03-01 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "0006_stage5_analyst_reports"
down_revision = "0005_stage4_sentiment_full"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("analyst_reports"):
        op.create_table(
            "analyst_reports",
            sa.Column("report_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("report_type", sa.String(length=16), nullable=False),
            sa.Column("period_key", sa.Date(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'generated'")),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("html_content", sa.Text(), nullable=True),
            sa.Column("json_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("inputs_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("email_error", sa.Text(), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("llm_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.UniqueConstraint("report_type", "period_key", name="uq_analyst_report_type_period"),
        )

    if _has_table("analyst_reports") and not _has_index("analyst_reports", "ix_analyst_reports_type_period"):
        op.create_index("ix_analyst_reports_type_period", "analyst_reports", ["report_type", "period_key"], unique=False)
    if _has_table("analyst_reports") and not _has_index("analyst_reports", "ix_analyst_reports_generated"):
        op.create_index("ix_analyst_reports_generated", "analyst_reports", ["generated_at"], unique=False)


def downgrade() -> None:
    if _has_table("analyst_reports"):
        if _has_index("analyst_reports", "ix_analyst_reports_generated"):
            op.drop_index("ix_analyst_reports_generated", table_name="analyst_reports")
        if _has_index("analyst_reports", "ix_analyst_reports_type_period"):
            op.drop_index("ix_analyst_reports_type_period", table_name="analyst_reports")
        op.drop_table("analyst_reports")
