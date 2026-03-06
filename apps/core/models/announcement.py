from __future__ import annotations

from datetime import datetime
import hashlib

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.core.database import Base


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (
        UniqueConstraint("announcement_id", name="uq_announcements_announcement_id"),
        Index("ix_announcements_ticker_date", "ticker", "announcement_date"),
        Index("ix_announcements_source_date", "source_id", "announcement_date"),
        Index("ix_announcements_alerted_date", "alerted", "announcement_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Legacy compatibility linkage.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)

    announcement_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    company_name: Mapped[str | None] = mapped_column("company", String(255), nullable=True)

    headline: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)

    announcement_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announcement_type: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    type_confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)

    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    classifier_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalizer_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Legacy columns retained for one transition window.
    legacy_title: Mapped[str | None] = mapped_column("title", Text, nullable=True)
    legacy_description: Mapped[str | None] = mapped_column("description", Text, nullable=True)
    legacy_source_name: Mapped[str | None] = mapped_column("source_name", String(128), nullable=True)
    legacy_source_url: Mapped[str | None] = mapped_column("source_url", Text, nullable=True)
    legacy_published_at: Mapped[datetime | None] = mapped_column("published_at", DateTime(timezone=True), nullable=True)
    legacy_detected_at: Mapped[datetime | None] = mapped_column("detected_at", DateTime(timezone=True), nullable=True)
    legacy_raw_data: Mapped[dict | None] = mapped_column("raw_data", JSONB, nullable=True)

    company = relationship("Company", back_populates="announcements")

    @staticmethod
    def sha256_hexdigest(*parts: str) -> str:
        payload = "|".join(part.strip() for part in parts if part is not None)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
