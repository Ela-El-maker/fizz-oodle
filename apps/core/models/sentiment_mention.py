from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database import Base


class SentimentMention(Base):
    __tablename__ = "sentiment_mentions"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_mention_hash"),
        Index("ix_mention_collected", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    platform: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)

    sentiment: Mapped[str] = mapped_column(String(16))  # bullish/bearish/neutral
    confidence: Mapped[float] = mapped_column(Numeric(5, 3), default=0)
    engagement: Mapped[int] = mapped_column(Integer, default=0)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    content_hash: Mapped[str] = mapped_column(String(64), unique=True)

    company = relationship("Company", back_populates="sentiment_mentions")
