"""Stage 2 announcements subsystem schema.

Revision ID: 0003_announcements_stage2
Revises: 0002_agent_runs_uuid_stage1
Create Date: 2026-03-01 02:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_announcements_stage2"
down_revision = "0002_agent_runs_uuid_stage1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Canonical announcements columns (Stage 2), added in a non-destructive way.
    op.add_column("announcements", sa.Column("announcement_id", sa.Text(), nullable=True))
    op.add_column("announcements", sa.Column("source_id", sa.String(length=128), nullable=True))
    op.add_column("announcements", sa.Column("ticker", sa.String(length=32), nullable=True))
    op.add_column("announcements", sa.Column("company", sa.String(length=255), nullable=True))
    op.add_column("announcements", sa.Column("headline", sa.Text(), nullable=True))
    op.add_column("announcements", sa.Column("url", sa.Text(), nullable=True))
    op.add_column("announcements", sa.Column("canonical_url", sa.Text(), nullable=True))
    op.add_column("announcements", sa.Column("announcement_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "announcements",
        sa.Column("type_confidence", sa.Numeric(precision=4, scale=3), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("announcements", sa.Column("details", sa.Text(), nullable=True))
    op.add_column("announcements", sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("announcements", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("announcements", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("announcements", sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("announcements", sa.Column("classifier_version", sa.String(length=64), nullable=True))
    op.add_column("announcements", sa.Column("normalizer_version", sa.String(length=64), nullable=True))

    # Backfill canonical columns from legacy fields.
    op.execute(
        """
        UPDATE announcements
        SET
            announcement_id = COALESCE(announcement_id, content_hash, md5('legacy-' || id::text)),
            source_id = COALESCE(
                source_id,
                NULLIF(regexp_replace(lower(COALESCE(source_name, '')), '[^a-z0-9]+', '_', 'g'), ''),
                'legacy_source'
            ),
            company = COALESCE(company, NULL),
            headline = COALESCE(headline, title, '(untitled)'),
            url = COALESCE(url, source_url, 'legacy://announcement/' || id::text),
            canonical_url = COALESCE(canonical_url, source_url, 'legacy://announcement/' || id::text),
            announcement_date = COALESCE(announcement_date, published_at, detected_at),
            details = COALESCE(details, description),
            raw_payload = COALESCE(raw_payload, raw_data, '{}'::jsonb),
            first_seen_at = COALESCE(first_seen_at, detected_at, now()),
            last_seen_at = COALESCE(last_seen_at, detected_at, now()),
            alerted_at = CASE WHEN alerted = true THEN COALESCE(alerted_at, detected_at, now()) ELSE alerted_at END
        """
    )

    op.alter_column("announcements", "announcement_id", nullable=False)
    op.alter_column("announcements", "source_id", nullable=False)
    op.alter_column("announcements", "headline", nullable=False)
    op.alter_column("announcements", "url", nullable=False)
    op.alter_column("announcements", "canonical_url", nullable=False)
    op.alter_column("announcements", "first_seen_at", nullable=False)
    op.alter_column("announcements", "last_seen_at", nullable=False)
    op.alter_column("announcements", "content_hash", nullable=True)

    op.create_unique_constraint("uq_announcements_announcement_id", "announcements", ["announcement_id"])
    op.create_index("ix_announcements_ticker_date", "announcements", ["ticker", "announcement_date"], unique=False)
    op.create_index("ix_announcements_source_date", "announcements", ["source_id", "announcement_date"], unique=False)
    op.create_index("ix_announcements_alerted_date", "announcements", ["alerted", "announcement_date"], unique=False)

    # Source health state table for breaker and observability.
    op.create_table(
        "source_health",
        sa.Column("source_id", sa.String(length=128), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("breaker_state", sa.Text(), nullable=False, server_default=sa.text("'closed'")),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    # Optional, but recommended for auditability.
    op.create_table(
        "announcement_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("announcement_id", sa.Text(), sa.ForeignKey("announcements.announcement_id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("asset_hash", sa.String(length=64), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_announcement_assets_announcement_id", "announcement_assets", ["announcement_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_announcement_assets_announcement_id", table_name="announcement_assets")
    op.drop_table("announcement_assets")

    op.drop_table("source_health")

    op.drop_index("ix_announcements_alerted_date", table_name="announcements")
    op.drop_index("ix_announcements_source_date", table_name="announcements")
    op.drop_index("ix_announcements_ticker_date", table_name="announcements")
    op.drop_constraint("uq_announcements_announcement_id", "announcements", type_="unique")

    op.alter_column("announcements", "content_hash", nullable=False)

    op.drop_column("announcements", "normalizer_version")
    op.drop_column("announcements", "classifier_version")
    op.drop_column("announcements", "alerted_at")
    op.drop_column("announcements", "last_seen_at")
    op.drop_column("announcements", "first_seen_at")
    op.drop_column("announcements", "raw_payload")
    op.drop_column("announcements", "details")
    op.drop_column("announcements", "type_confidence")
    op.drop_column("announcements", "announcement_date")
    op.drop_column("announcements", "canonical_url")
    op.drop_column("announcements", "url")
    op.drop_column("announcements", "headline")
    op.drop_column("announcements", "company")
    op.drop_column("announcements", "ticker")
    op.drop_column("announcements", "source_id")
    op.drop_column("announcements", "announcement_id")
