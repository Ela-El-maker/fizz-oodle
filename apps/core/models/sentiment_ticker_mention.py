from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class SentimentTickerMention(Base):
    __tablename__ = "sentiment_ticker_mentions"
    __table_args__ = (
        UniqueConstraint("post_id", "ticker", name="uq_sent_ticker_post_ticker"),
        Index("ix_sent_ticker_scored", "ticker", "scored_at"),
        Index("ix_sent_ticker_label_scored", "sentiment_label", "scored_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sentiment_score: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    sentiment_label: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False)
    source_weight: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False)
    reasons: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
