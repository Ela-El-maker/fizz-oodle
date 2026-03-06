from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class SourceHealth(Base):
    __tablename__ = "source_health"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breaker_state: Mapped[str] = mapped_column(Text, nullable=False, default="closed")
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
