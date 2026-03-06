"""init

Revision ID: 0001
Revises: 
Create Date: 2026-02-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("ir_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("ticker", name="uq_companies_ticker"),
    )
    op.create_index("ix_companies_ticker", "companies", ["ticker"], unique=True)

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("price", sa.Numeric(16, 4), nullable=True),
        sa.Column("prev_close", sa.Numeric(16, 4), nullable=True),
        sa.Column("change_val", sa.Numeric(16, 4), nullable=True),
        sa.Column("pct_change", sa.Numeric(8, 3), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("company_id", "snapshot_date", name="uq_price_company_date"),
    )
    op.create_index("ix_price_snapshot_date", "price_snapshots", ["snapshot_date"], unique=False)
    op.create_index("ix_price_company", "price_snapshots", ["company_id"], unique=False)

    op.create_table(
        "forex_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pair", sa.String(length=16), nullable=False),
        sa.Column("rate", sa.Numeric(16, 6), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("pair", "snapshot_date", name="uq_fx_pair_date"),
    )
    op.create_index("ix_fx_snapshot_date", "forex_rates", ["snapshot_date"], unique=False)

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("content_hash", name="uq_news_hash"),
    )
    op.create_index("ix_news_company", "news_articles", ["company_id"], unique=False)
    op.create_index("ix_news_published", "news_articles", ["published_at"], unique=False)

    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("announcement_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("alerted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("content_hash", name="uq_announcement_hash"),
    )
    op.create_index("ix_announcement_company", "announcements", ["company_id"], unique=False)
    op.create_index("ix_announcement_detected", "announcements", ["detected_at"], unique=False)

    op.create_table(
        "sentiment_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("bullish_pct", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("bearish_pct", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("neutral_pct", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sentiment_score", sa.Numeric(6, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("prev_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("score_delta", sa.Numeric(6, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("company_id", "week_start", name="uq_sent_company_week"),
    )
    op.create_index("ix_sent_week", "sentiment_snapshots", ["week_start"], unique=False)
    op.create_index("ix_sent_company", "sentiment_snapshots", ["company_id"], unique=False)

    op.create_table(
        "sentiment_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author", sa.String(length=128), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("engagement", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("content_hash", name="uq_mention_hash"),
    )
    op.create_index("ix_mention_company", "sentiment_mentions", ["company_id"], unique=False)
    op.create_index("ix_mention_collected", "sentiment_mentions", ["collected_at"], unique=False)

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_agent_run_started", "agent_runs", ["started_at"], unique=False)
    op.create_index("ix_agent_run_name", "agent_runs", ["agent_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_run_name", table_name="agent_runs")
    op.drop_index("ix_agent_run_started", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("ix_mention_collected", table_name="sentiment_mentions")
    op.drop_index("ix_mention_company", table_name="sentiment_mentions")
    op.drop_table("sentiment_mentions")

    op.drop_index("ix_sent_company", table_name="sentiment_snapshots")
    op.drop_index("ix_sent_week", table_name="sentiment_snapshots")
    op.drop_table("sentiment_snapshots")

    op.drop_index("ix_announcement_detected", table_name="announcements")
    op.drop_index("ix_announcement_company", table_name="announcements")
    op.drop_table("announcements")

    op.drop_index("ix_news_published", table_name="news_articles")
    op.drop_index("ix_news_company", table_name="news_articles")
    op.drop_table("news_articles")

    op.drop_index("ix_fx_snapshot_date", table_name="forex_rates")
    op.drop_table("forex_rates")

    op.drop_index("ix_price_company", table_name="price_snapshots")
    op.drop_index("ix_price_snapshot_date", table_name="price_snapshots")
    op.drop_table("price_snapshots")

    op.drop_index("ix_companies_ticker", table_name="companies")
    op.drop_table("companies")
