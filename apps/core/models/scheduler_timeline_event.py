from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class SchedulerTimelineEvent(Base):
    __tablename__ = "scheduler_timeline_events"
    __table_args__ = (
        Index("ix_scheduler_timeline_events_time", "event_time"),
        Index("ix_scheduler_timeline_events_agent_time", "agent_name", "event_time"),
        Index("ix_scheduler_timeline_events_schedule_time", "schedule_key", "event_time"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="scheduler")
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    schedule_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

