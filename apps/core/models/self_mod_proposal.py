from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class SelfModificationProposal(Base):
    __tablename__ = "self_mod_proposals"

    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="platform")
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    changes_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    auto_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="learning_engine")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

