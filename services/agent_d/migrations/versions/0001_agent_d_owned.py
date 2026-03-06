"""agent_d owned schema baseline."""

from __future__ import annotations

from alembic import op

from apps.core.database import Base
from apps.core import models as _models  # noqa: F401

revision = "0001_agent_d_owned"
down_revision = None
branch_labels = None
depends_on = None

TABLES = ['analyst_reports']


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
