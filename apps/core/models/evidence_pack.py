from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class EvidencePack(Base):
    __tablename__ = "evidence_packs"
    __table_args__ = (
        Index("ix_evidence_packs_scope_latest", "scope_type", "scope_id", "created_at"),
    )

    pack_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)

    seed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sources_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    entity_resolution_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    coverage_score: Mapped[float | None] = mapped_column(nullable=True)
    freshness_score: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
