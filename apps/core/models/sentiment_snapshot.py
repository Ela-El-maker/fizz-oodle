from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database import Base


class SentimentSnapshot(Base):
    __tablename__ = "sentiment_snapshots"
    __table_args__ = (
        UniqueConstraint("company_id", "week_start", name="uq_sent_company_week"),
        Index("ix_sent_week", "week_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    week_start: Mapped[date] = mapped_column(Date)

    bullish_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    bearish_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    neutral_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)

    sentiment_score: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    prev_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    score_delta: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    company = relationship("Company", back_populates="sentiment_snapshots")
