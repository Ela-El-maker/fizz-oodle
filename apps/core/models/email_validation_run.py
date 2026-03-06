from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class EmailValidationRun(Base):
    __tablename__ = "email_validation_runs"
    __table_args__ = (
        UniqueConstraint("window", "period_key", name="uq_email_validation_window_period"),
        Index("ix_email_validation_runs_window_period", "window", "period_key"),
        Index("ix_email_validation_runs_started", "started_at"),
    )

    validation_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    window: Mapped[str] = mapped_column(String(16), nullable=False)  # daily|weekly
    period_key: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|partial|fail
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSONB, default=dict)

