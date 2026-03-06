from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class PatternOccurrence(Base):
    __tablename__ = "pattern_occurrence"
    __table_args__ = (UniqueConstraint("pattern_id", "observed_on", name="uq_pattern_occurrence_date"),)

    occurrence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pattern_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pattern.pattern_id"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    observed_on: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_refs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

