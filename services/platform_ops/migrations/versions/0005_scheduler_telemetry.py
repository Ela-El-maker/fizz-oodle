"""platform_ops scheduler telemetry tables."""

from __future__ import annotations

from alembic import op

from apps.core.database import Base
from apps.core import models as _models  # noqa: F401

revision = "0005_scheduler_telemetry"
down_revision = "0004_self_mod_ops"
branch_labels = None
depends_on = None

TABLES = [
    "scheduler_dispatches",
    "run_commands",
    "scheduler_timeline_events",
]


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        table = Base.metadata.tables[name]
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        table = Base.metadata.tables[name]
        table.drop(bind=bind, checkfirst=True)

