from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class SchedulerDispatch(Base):
    __tablename__ = "scheduler_dispatches"
    __table_args__ = (
        Index("ix_scheduler_dispatches_schedule_dispatched", "schedule_key", "dispatched_at"),
        Index("ix_scheduler_dispatches_agent_dispatched", "agent_name", "dispatched_at"),
        Index("ix_scheduler_dispatches_run_id", "run_id"),
    )

    dispatch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    command_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scheduled_for_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    dispatch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_kwargs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

