from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    exchange: Mapped[str] = mapped_column(String(32))  # NSE/JSE/NGX
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ir_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    price_snapshots = relationship("PriceSnapshot", back_populates="company")
    announcements = relationship("Announcement", back_populates="company")
    sentiment_snapshots = relationship("SentimentSnapshot", back_populates="company")
    sentiment_mentions = relationship("SentimentMention", back_populates="company")
    news_articles = relationship("NewsArticle", back_populates="company")
