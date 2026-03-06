from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class IndexDaily(Base):
    __tablename__ = "index_daily"
    __table_args__ = (
        UniqueConstraint("date", "index_name", "source_id", name="uq_index_daily_date_name_source"),
        Index("ix_index_daily_date", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    index_name: Mapped[str] = mapped_column(String(64), nullable=False)

    value: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    change_val: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    pct_change: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
