"""Stage 4 sentiment full-grade contracts.

Revision ID: 0005_stage4_sentiment_full
Revises: 0004_stage3_daily_briefing
Create Date: 2026-03-01 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "0005_stage4_sentiment_full"
down_revision = "0004_stage3_daily_briefing"
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
    if not _has_table("sentiment_raw_posts"):
        op.create_table(
            "sentiment_raw_posts",
            sa.Column("post_id", sa.Text(), primary_key=True),
            sa.Column("source_id", sa.String(length=128), nullable=False),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("canonical_url", sa.Text(), nullable=True),
            sa.Column("author", sa.String(length=255), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if _has_table("sentiment_raw_posts") and not _has_index("sentiment_raw_posts", "ix_sent_raw_source_published"):
        op.create_index("ix_sent_raw_source_published", "sentiment_raw_posts", ["source_id", "published_at"], unique=False)
    if _has_table("sentiment_raw_posts") and not _has_index("sentiment_raw_posts", "ix_sent_raw_fetched"):
        op.create_index("ix_sent_raw_fetched", "sentiment_raw_posts", ["fetched_at"], unique=False)

    if not _has_table("sentiment_ticker_mentions"):
        op.create_table(
            "sentiment_ticker_mentions",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("post_id", sa.Text(), nullable=False),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("company_name", sa.String(length=255), nullable=True),
            sa.Column("sentiment_score", sa.Numeric(6, 3), nullable=False),
            sa.Column("sentiment_label", sa.String(length=16), nullable=False),
            sa.Column("confidence", sa.Numeric(5, 3), nullable=False),
            sa.Column("source_weight", sa.Numeric(5, 3), nullable=False),
            sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("model_version", sa.String(length=64), nullable=False),
            sa.Column("llm_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["post_id"], ["sentiment_raw_posts.post_id"], ondelete="CASCADE"),
            sa.UniqueConstraint("post_id", "ticker", name="uq_sent_ticker_post_ticker"),
        )
    if _has_table("sentiment_ticker_mentions") and not _has_index("sentiment_ticker_mentions", "ix_sent_ticker_scored"):
        op.create_index("ix_sent_ticker_scored", "sentiment_ticker_mentions", ["ticker", "scored_at"], unique=False)
    if _has_table("sentiment_ticker_mentions") and not _has_index("sentiment_ticker_mentions", "ix_sent_ticker_label_scored"):
        op.create_index("ix_sent_ticker_label_scored", "sentiment_ticker_mentions", ["sentiment_label", "scored_at"], unique=False)
    if _has_table("sentiment_ticker_mentions") and not _has_index("sentiment_ticker_mentions", "ix_sent_ticker_post"):
        op.create_index("ix_sent_ticker_post", "sentiment_ticker_mentions", ["post_id"], unique=False)

    if not _has_table("sentiment_weekly"):
        op.create_table(
            "sentiment_weekly",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("week_start", sa.Date(), nullable=False),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("company_name", sa.String(length=255), nullable=False),
            sa.Column("mentions_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("bullish_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("bearish_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("neutral_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("bullish_pct", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("bearish_pct", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("neutral_pct", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("weighted_score", sa.Numeric(6, 3), nullable=False, server_default=sa.text("0")),
            sa.Column("confidence", sa.Numeric(5, 3), nullable=False, server_default=sa.text("0")),
            sa.Column("top_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("notable_quotes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("wow_delta", sa.Numeric(6, 3), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("week_start", "ticker", name="uq_sent_weekly_week_ticker"),
        )
    if _has_table("sentiment_weekly") and not _has_index("sentiment_weekly", "ix_sent_weekly_week"):
        op.create_index("ix_sent_weekly_week", "sentiment_weekly", ["week_start"], unique=False)
    if _has_table("sentiment_weekly") and not _has_index("sentiment_weekly", "ix_sent_weekly_ticker_week"):
        op.create_index("ix_sent_weekly_ticker_week", "sentiment_weekly", ["ticker", "week_start"], unique=False)

    if not _has_table("sentiment_digest_reports"):
        op.create_table(
            "sentiment_digest_reports",
            sa.Column("week_start", sa.Date(), primary_key=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'generated'")),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("html_content", sa.Text(), nullable=True),
            sa.Column("html_path", sa.Text(), nullable=True),
            sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("email_error", sa.Text(), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
        )
    if _has_table("sentiment_digest_reports") and not _has_index("sentiment_digest_reports", "ix_sent_digest_week"):
        op.create_index("ix_sent_digest_week", "sentiment_digest_reports", ["week_start"], unique=False)


def downgrade() -> None:
    if _has_table("sentiment_digest_reports"):
        if _has_index("sentiment_digest_reports", "ix_sent_digest_week"):
            op.drop_index("ix_sent_digest_week", table_name="sentiment_digest_reports")
        op.drop_table("sentiment_digest_reports")

    if _has_table("sentiment_weekly"):
        if _has_index("sentiment_weekly", "ix_sent_weekly_ticker_week"):
            op.drop_index("ix_sent_weekly_ticker_week", table_name="sentiment_weekly")
        if _has_index("sentiment_weekly", "ix_sent_weekly_week"):
            op.drop_index("ix_sent_weekly_week", table_name="sentiment_weekly")
        op.drop_table("sentiment_weekly")

    if _has_table("sentiment_ticker_mentions"):
        if _has_index("sentiment_ticker_mentions", "ix_sent_ticker_post"):
            op.drop_index("ix_sent_ticker_post", table_name="sentiment_ticker_mentions")
        if _has_index("sentiment_ticker_mentions", "ix_sent_ticker_label_scored"):
            op.drop_index("ix_sent_ticker_label_scored", table_name="sentiment_ticker_mentions")
        if _has_index("sentiment_ticker_mentions", "ix_sent_ticker_scored"):
            op.drop_index("ix_sent_ticker_scored", table_name="sentiment_ticker_mentions")
        op.drop_table("sentiment_ticker_mentions")

    if _has_table("sentiment_raw_posts"):
        if _has_index("sentiment_raw_posts", "ix_sent_raw_fetched"):
            op.drop_index("ix_sent_raw_fetched", table_name="sentiment_raw_posts")
        if _has_index("sentiment_raw_posts", "ix_sent_raw_source_published"):
            op.drop_index("ix_sent_raw_source_published", table_name="sentiment_raw_posts")
        op.drop_table("sentiment_raw_posts")

