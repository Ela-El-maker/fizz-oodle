from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class SentimentDigestReport(Base):
    __tablename__ = "sentiment_digest_reports"
    __table_args__ = (Index("ix_sent_digest_week", "week_start"),)

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generated")
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

