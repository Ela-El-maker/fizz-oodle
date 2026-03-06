from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class RunCommand(Base):
    __tablename__ = "run_commands"
    __table_args__ = (
        Index("ix_run_commands_agent_requested", "agent_name", "requested_at"),
        Index("ix_run_commands_run_id", "run_id"),
        Index("ix_run_commands_trigger_requested", "trigger_type", "requested_at"),
    )

    command_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    schedule_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    report_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    run_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    force_send: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    email_recipients_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

