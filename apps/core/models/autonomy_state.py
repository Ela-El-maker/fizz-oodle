from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database import Base


class AutonomyState(Base):
    __tablename__ = "autonomy_state"

    state_key: Mapped[str] = mapped_column(String(64), primary_key=True, default="global")
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_policies: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_policy_recompute_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
