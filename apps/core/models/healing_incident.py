from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class HealingIncident(Base):
    __tablename__ = "healing_incidents"

    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    failure_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False, default="applied")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
