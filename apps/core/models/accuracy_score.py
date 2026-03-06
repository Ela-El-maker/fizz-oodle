from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class AccuracyScore(Base):
    __tablename__ = "accuracy_score"
    __table_args__ = (UniqueConstraint("agent_name", "period_key", "ticker", name="uq_accuracy_agent_period_ticker"),)

    score_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period_key: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="MARKET")
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    grade: Mapped[str] = mapped_column(String(24), nullable=False, default="insufficient")
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

