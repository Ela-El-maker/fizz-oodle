from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class SentimentWeekly(Base):
    __tablename__ = "sentiment_weekly"
    __table_args__ = (
        UniqueConstraint("week_start", "ticker", name="uq_sent_weekly_week_ticker"),
        Index("ix_sent_weekly_week", "week_start"),
        Index("ix_sent_weekly_ticker_week", "ticker", "week_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mentions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bullish_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bearish_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bullish_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    bearish_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    neutral_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    weighted_score: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False, default=0)
    top_sources: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notable_quotes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    wow_delta: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

