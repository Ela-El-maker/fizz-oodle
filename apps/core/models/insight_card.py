from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class InsightCard(Base):
    __tablename__ = "insight_cards"
    __table_args__ = (
        Index("ix_insight_cards_scope_latest", "scope_type", "scope_id", "generated_at"),
        Index("ix_insight_cards_ticker_latest", "ticker", "generated_at"),
        Index("ix_insight_cards_status", "status"),
    )

    card_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    scope_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    sections_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quality_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    llm_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_mode: Mapped[str] = mapped_column(String(64), nullable=False, default="none")
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
