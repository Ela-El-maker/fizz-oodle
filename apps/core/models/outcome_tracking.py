from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, Float, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class OutcomeTracking(Base):
    __tablename__ = "outcome_tracking"
    __table_args__ = (UniqueConstraint("signal_ref", "ticker", name="uq_outcome_signal_ticker"),)

    outcome_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_agent: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    predicted_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actual_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    change_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str] = mapped_column(String(24), nullable=False, default="insufficient", index=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

