"""platform_ops email validation audit tables."""

from __future__ import annotations

from alembic import op

from apps.core.database import Base
from apps.core import models as _models  # noqa: F401

revision = "0002_email_validation_ops"
down_revision = "0001_platform_ops_owned"
branch_labels = None
depends_on = None

TABLES = [
    "email_validation_runs",
    "email_validation_steps",
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

