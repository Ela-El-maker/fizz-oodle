from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class Pattern(Base):
    __tablename__ = "pattern"
    __table_args__ = (UniqueConstraint("ticker", "pattern_type", name="uq_pattern_ticker_type"),)

    pattern_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    pattern_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate", index=True)
    confidence_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_impact_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_impact_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

