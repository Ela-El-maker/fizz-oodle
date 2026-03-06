from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class AnalystReport(Base):
    __tablename__ = "analyst_reports"
    __table_args__ = (
        UniqueConstraint("report_type", "period_key", name="uq_analyst_report_type_period"),
        Index("ix_analyst_reports_type_period", "report_type", "period_key"),
        Index("ix_analyst_reports_generated", "generated_at"),
    )

    report_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    period_key: Mapped[date] = mapped_column(Date, nullable=False)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generated")

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    json_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    inputs_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
