from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class ForexRate(Base):
    __tablename__ = "forex_rates"
    __table_args__ = (
        UniqueConstraint("pair", "snapshot_date", name="uq_fx_pair_date"),
        Index("ix_fx_snapshot_date", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pair: Mapped[str] = mapped_column(String(16))  # KES/USD
    rate: Mapped[float] = mapped_column(Numeric(16, 6))
    snapshot_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
