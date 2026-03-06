"""Stage 6 archivist tables.

Revision ID: 0007_stage6_archivist_tables
Revises: 0006_stage5_analyst_reports
Create Date: 2026-03-01 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "0007_stage6_archivist_tables"
down_revision = "0006_stage5_analyst_reports"
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
    if not _has_table("pattern"):
        op.create_table(
            "pattern",
            sa.Column("pattern_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("pattern_type", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'candidate'")),
            sa.Column("confidence_pct", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("accuracy_pct", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("avg_impact_1d", sa.Float(), nullable=True),
            sa.Column("avg_impact_5d", sa.Float(), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("ticker", "pattern_type", name="uq_pattern_ticker_type"),
        )

    if not _has_table("pattern_occurrence"):
        op.create_table(
            "pattern_occurrence",
            sa.Column("occurrence_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("pattern_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pattern.pattern_id"), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("observed_on", sa.Date(), nullable=False),
            sa.Column("strength", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("source_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("pattern_id", "observed_on", name="uq_pattern_occurrence_date"),
        )

    if not _has_table("accuracy_score"):
        op.create_table(
            "accuracy_score",
            sa.Column("score_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("agent_name", sa.String(length=32), nullable=False),
            sa.Column("period_key", sa.Date(), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False, server_default=sa.text("'MARKET'")),
            sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("accuracy_pct", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("grade", sa.String(length=24), nullable=False, server_default=sa.text("'insufficient'")),
            sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("agent_name", "period_key", "ticker", name="uq_accuracy_agent_period_ticker"),
        )

    if not _has_table("outcome_tracking"):
        op.create_table(
            "outcome_tracking",
            sa.Column("outcome_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("signal_ref", sa.String(length=128), nullable=False),
            sa.Column("source_agent", sa.String(length=32), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("predicted_direction", sa.String(length=16), nullable=True),
            sa.Column("actual_direction", sa.String(length=16), nullable=True),
            sa.Column("change_1d", sa.Float(), nullable=True),
            sa.Column("change_5d", sa.Float(), nullable=True),
            sa.Column("grade", sa.String(length=24), nullable=False, server_default=sa.text("'insufficient'")),
            sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("signal_ref", "ticker", name="uq_outcome_signal_ticker"),
        )

    if not _has_table("impact_stat"):
        op.create_table(
            "impact_stat",
            sa.Column("impact_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("announcement_type", sa.String(length=64), nullable=False),
            sa.Column("period_key", sa.Date(), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("avg_change_1d", sa.Float(), nullable=True),
            sa.Column("avg_change_5d", sa.Float(), nullable=True),
            sa.Column("avg_change_30d", sa.Float(), nullable=True),
            sa.Column("positive_rate", sa.Float(), nullable=True),
            sa.Column("negative_rate", sa.Float(), nullable=True),
            sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("announcement_type", "period_key", name="uq_impact_type_period"),
        )

    if not _has_table("archive_run"):
        op.create_table(
            "archive_run",
            sa.Column("archive_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("run_type", sa.String(length=16), nullable=False),
            sa.Column("period_key", sa.Date(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'generated'")),
            sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("html_content", sa.Text(), nullable=True),
            sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("email_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("run_type", "period_key", name="uq_archive_run_type_period"),
        )

    if _has_table("pattern") and not _has_index("pattern", "ix_pattern_status"):
        op.create_index("ix_pattern_status", "pattern", ["status"], unique=False)
    if _has_table("pattern") and not _has_index("pattern", "ix_pattern_ticker"):
        op.create_index("ix_pattern_ticker", "pattern", ["ticker"], unique=False)
    if _has_table("pattern_occurrence") and not _has_index("pattern_occurrence", "ix_pattern_occurrence_ticker"):
        op.create_index("ix_pattern_occurrence_ticker", "pattern_occurrence", ["ticker"], unique=False)
    if _has_table("impact_stat") and not _has_index("impact_stat", "ix_impact_stat_type"):
        op.create_index("ix_impact_stat_type", "impact_stat", ["announcement_type"], unique=False)
    if _has_table("archive_run") and not _has_index("archive_run", "ix_archive_run_period"):
        op.create_index("ix_archive_run_period", "archive_run", ["run_type", "period_key"], unique=False)


def downgrade() -> None:
    if _has_table("archive_run"):
        if _has_index("archive_run", "ix_archive_run_period"):
            op.drop_index("ix_archive_run_period", table_name="archive_run")
        op.drop_table("archive_run")
    if _has_table("impact_stat"):
        if _has_index("impact_stat", "ix_impact_stat_type"):
            op.drop_index("ix_impact_stat_type", table_name="impact_stat")
        op.drop_table("impact_stat")
    if _has_table("outcome_tracking"):
        op.drop_table("outcome_tracking")
    if _has_table("accuracy_score"):
        op.drop_table("accuracy_score")
    if _has_table("pattern_occurrence"):
        if _has_index("pattern_occurrence", "ix_pattern_occurrence_ticker"):
            op.drop_index("ix_pattern_occurrence_ticker", table_name="pattern_occurrence")
        op.drop_table("pattern_occurrence")
    if _has_table("pattern"):
        if _has_index("pattern", "ix_pattern_ticker"):
            op.drop_index("ix_pattern_ticker", table_name="pattern")
        if _has_index("pattern", "ix_pattern_status"):
            op.drop_index("ix_pattern_status", table_name="pattern")
        op.drop_table("pattern")

