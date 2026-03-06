from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Date, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class ArchiveRun(Base):
    __tablename__ = "archive_run"
    __table_args__ = (UniqueConstraint("run_type", "period_key", name="uq_archive_run_type_period"),)

    archive_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # weekly|monthly
    period_key: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="generated")
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    html_content: Mapped[str | None] = mapped_column(String, nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

