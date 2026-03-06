from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class PriceDaily(Base):
    __tablename__ = "prices_daily"
    __table_args__ = (
        UniqueConstraint("date", "ticker", "source_id", name="uq_prices_daily_date_ticker_source"),
        Index("ix_prices_daily_ticker_date", "ticker", "date"),
        Index("ix_prices_daily_date", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)

    close: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    open: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    volume: Mapped[float | None] = mapped_column(Numeric(18, 3), nullable=True)

    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="KES")
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
