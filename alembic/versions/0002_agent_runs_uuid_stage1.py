"""Stage 1 run lifecycle contract: UUID run_id + status/metrics bridge.

Revision ID: 0002_agent_runs_uuid_stage1
Revises: 0001_init
Create Date: 2026-03-01 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0002_agent_runs_uuid_stage1"
down_revision = "0001"
branch_labels = None
depends_on = None


STATUS_BACKFILL_SQL = """
UPDATE agent_runs
SET status = CASE lower(coalesce(outcome, ''))
    WHEN 'running' THEN 'running'
    WHEN 'started' THEN 'running'
    WHEN 'success' THEN 'success'
    WHEN 'partial' THEN 'partial'
    WHEN 'fail' THEN 'fail'
    WHEN 'failed' THEN 'fail'
    ELSE 'fail'
END
"""


OUTCOME_BACKFILL_SQL = """
UPDATE agent_runs
SET outcome = CASE lower(coalesce(status, ''))
    WHEN 'running' THEN 'running'
    WHEN 'success' THEN 'success'
    WHEN 'partial' THEN 'partial'
    WHEN 'fail' THEN 'fail'
    ELSE 'unknown'
END
"""


def upgrade() -> None:
    # Needed for gen_random_uuid() on PostgreSQL.
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # New canonical run identifier.
    op.add_column("agent_runs", sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("UPDATE agent_runs SET run_id = gen_random_uuid() WHERE run_id IS NULL")
    op.alter_column("agent_runs", "run_id", nullable=False)

    # Move primary key from legacy int id to UUID run_id.
    op.execute("ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_pkey")
    op.create_primary_key("agent_runs_pkey", "agent_runs", ["run_id"])
    op.alter_column("agent_runs", "id", nullable=True)

    # Canonical status/metrics contract with compatibility bridge to legacy fields.
    op.add_column("agent_runs", sa.Column("status", sa.String(length=16), nullable=True))
    op.execute(STATUS_BACKFILL_SQL)
    op.alter_column("agent_runs", "status", nullable=False, server_default=sa.text("'running'"))

    op.add_column("agent_runs", sa.Column("errors_count", sa.Integer(), nullable=False, server_default=sa.text("0")))

    op.add_column("agent_runs", sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.execute("UPDATE agent_runs SET metrics = COALESCE(metadata, '{}'::jsonb) WHERE metrics IS NULL")
    op.alter_column("agent_runs", "metrics", nullable=False, server_default=sa.text("'{}'::jsonb"))


def downgrade() -> None:
    # Restore legacy columns from canonical columns before dropping them.
    op.execute(OUTCOME_BACKFILL_SQL)
    op.execute("UPDATE agent_runs SET metadata = COALESCE(metrics, '{}'::jsonb)")

    # Ensure legacy integer id exists for PK restoration.
    op.execute(
        """
        WITH null_rows AS (
            SELECT run_id,
                   ROW_NUMBER() OVER (ORDER BY started_at, run_id) +
                   COALESCE((SELECT MAX(id) FROM agent_runs), 0) AS generated_id
            FROM agent_runs
            WHERE id IS NULL
        )
        UPDATE agent_runs ar
        SET id = nr.generated_id
        FROM null_rows nr
        WHERE ar.run_id = nr.run_id
        """
    )

    op.execute("ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_pkey")
    op.alter_column("agent_runs", "id", nullable=False)
    op.create_primary_key("agent_runs_pkey", "agent_runs", ["id"])

    op.drop_column("agent_runs", "metrics")
    op.drop_column("agent_runs", "errors_count")
    op.drop_column("agent_runs", "status")
    op.drop_column("agent_runs", "run_id")
