"""Stage 3 daily briefing data contracts.

Revision ID: 0004_stage3_daily_briefing
Revises: 0003_announcements_stage2
Create Date: 2026-03-01 11:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect


revision = "0004_stage3_daily_briefing"
down_revision = "0003_announcements_stage2"
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
    if not _has_table("prices_daily"):
        op.create_table(
            "prices_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("ticker", sa.String(length=32), nullable=False),
            sa.Column("close", sa.Numeric(16, 4), nullable=True),
            sa.Column("open", sa.Numeric(16, 4), nullable=True),
            sa.Column("high", sa.Numeric(16, 4), nullable=True),
            sa.Column("low", sa.Numeric(16, 4), nullable=True),
            sa.Column("volume", sa.Numeric(18, 3), nullable=True),
            sa.Column("currency", sa.String(length=16), nullable=False, server_default=sa.text("'KES'")),
            sa.Column("source_id", sa.String(length=64), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.UniqueConstraint("date", "ticker", "source_id", name="uq_prices_daily_date_ticker_source"),
        )
    if _has_table("prices_daily") and not _has_index("prices_daily", "ix_prices_daily_ticker_date"):
        op.create_index("ix_prices_daily_ticker_date", "prices_daily", ["ticker", "date"], unique=False)
    if _has_table("prices_daily") and not _has_index("prices_daily", "ix_prices_daily_date"):
        op.create_index("ix_prices_daily_date", "prices_daily", ["date"], unique=False)

    if not _has_table("index_daily"):
        op.create_table(
            "index_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("index_name", sa.String(length=64), nullable=False),
            sa.Column("value", sa.Numeric(16, 4), nullable=True),
            sa.Column("change_val", sa.Numeric(16, 4), nullable=True),
            sa.Column("pct_change", sa.Numeric(8, 3), nullable=True),
            sa.Column("source_id", sa.String(length=64), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.UniqueConstraint("date", "index_name", "source_id", name="uq_index_daily_date_name_source"),
        )
    if _has_table("index_daily") and not _has_index("index_daily", "ix_index_daily_date"):
        op.create_index("ix_index_daily_date", "index_daily", ["date"], unique=False)

    if not _has_table("fx_daily"):
        op.create_table(
            "fx_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("pair", sa.String(length=32), nullable=False),
            sa.Column("rate", sa.Numeric(16, 6), nullable=False),
            sa.Column("source_id", sa.String(length=64), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.UniqueConstraint("date", "pair", "source_id", name="uq_fx_daily_date_pair_source"),
        )
    if _has_table("fx_daily") and not _has_index("fx_daily", "ix_fx_daily_date"):
        op.create_index("ix_fx_daily_date", "fx_daily", ["date"], unique=False)

    if not _has_table("news_headlines_daily"):
        op.create_table(
            "news_headlines_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("source_id", sa.String(length=64), nullable=False),
            sa.Column("headline", sa.Text(), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("date", "source_id", "url", name="uq_news_headline_daily_date_source_url"),
        )
    if _has_table("news_headlines_daily") and not _has_index("news_headlines_daily", "ix_news_headline_daily_date"):
        op.create_index("ix_news_headline_daily_date", "news_headlines_daily", ["date"], unique=False)

    if not _has_table("daily_briefings"):
        op.create_table(
            "daily_briefings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("briefing_date", sa.Date(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'generated'")),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("html_content", sa.Text(), nullable=True),
            sa.Column("html_path", sa.Text(), nullable=True),
            sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("email_error", sa.Text(), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.UniqueConstraint("briefing_date", name="uq_daily_briefing_date"),
        )
    if _has_table("daily_briefings") and not _has_index("daily_briefings", "ix_daily_briefings_date"):
        op.create_index("ix_daily_briefings_date", "daily_briefings", ["briefing_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_daily_briefings_date", table_name="daily_briefings")
    op.drop_table("daily_briefings")

    op.drop_index("ix_news_headline_daily_date", table_name="news_headlines_daily")
    op.drop_table("news_headlines_daily")

    op.drop_index("ix_fx_daily_date", table_name="fx_daily")
    op.drop_table("fx_daily")

    op.drop_index("ix_index_daily_date", table_name="index_daily")
    op.drop_table("index_daily")

    op.drop_index("ix_prices_daily_date", table_name="prices_daily")
    op.drop_index("ix_prices_daily_ticker_date", table_name="prices_daily")
    op.drop_table("prices_daily")
