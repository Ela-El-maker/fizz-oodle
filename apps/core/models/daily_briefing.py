from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"
    __table_args__ = (
        UniqueConstraint("briefing_date", name="uq_daily_briefing_date"),
        Index("ix_daily_briefings_date", "briefing_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    briefing_date: Mapped[date] = mapped_column(Date, nullable=False)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generated")

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
