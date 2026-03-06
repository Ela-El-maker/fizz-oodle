from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_run_started", "started_at"),
        Index("ix_agent_run_name", "agent_name"),
    )

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # legacy compatibility column
    agent_name: Mapped[str] = mapped_column(String(64))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="running")  # running/success/partial/fail
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_new: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)

    _legacy_outcome: Mapped[str | None] = mapped_column("outcome", String(16), nullable=True)
    _legacy_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    @property
    def outcome(self) -> str:
        """Compatibility bridge for legacy code paths using `outcome`."""
        return self.status

    @outcome.setter
    def outcome(self, value: str) -> None:
        self.status = value
        self._legacy_outcome = value

    @property
    def legacy_metadata(self) -> dict:
        """Compatibility bridge for legacy code paths using the old metadata payload."""
        return self.metrics or {}
