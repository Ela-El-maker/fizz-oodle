from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class ImpactStat(Base):
    __tablename__ = "impact_stat"
    __table_args__ = (UniqueConstraint("announcement_type", "period_key", name="uq_impact_type_period"),)

    impact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    announcement_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    period_key: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_change_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_change_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_change_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    positive_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    negative_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

