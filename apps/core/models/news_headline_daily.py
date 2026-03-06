from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class NewsHeadlineDaily(Base):
    __tablename__ = "news_headlines_daily"
    __table_args__ = (
        UniqueConstraint("date", "source_id", "url", name="uq_news_headline_daily_date_source_url"),
        Index("ix_news_headline_daily_date", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)

    headline: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
