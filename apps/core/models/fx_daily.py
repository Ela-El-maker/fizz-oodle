from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class FxDaily(Base):
    __tablename__ = "fx_daily"
    __table_args__ = (
        UniqueConstraint("date", "pair", "source_id", name="uq_fx_daily_date_pair_source"),
        Index("ix_fx_daily_date", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(16, 6), nullable=False)

    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
