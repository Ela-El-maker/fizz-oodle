from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database import Base


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("company_id", "snapshot_date", name="uq_price_company_date"),
        Index("ix_price_snapshot_date", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)

    price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    change_val: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    pct_change: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)

    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(64), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    company = relationship("Company", back_populates="price_snapshots")
