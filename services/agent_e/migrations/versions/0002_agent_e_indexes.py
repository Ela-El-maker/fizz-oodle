"""agent_e archivist query indexes."""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0002_agent_e_indexes"
down_revision = "0001_agent_e_owned"
branch_labels = None
depends_on = None


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_index("pattern", "ix_pattern_active_status_updated"):
        op.create_index(
            "ix_pattern_active_status_updated",
            "pattern",
            ["active", "status", "updated_at"],
            unique=False,
        )
    if not _has_index("pattern_occurrence", "ix_pattern_occurrence_ticker_observed"):
        op.create_index(
            "ix_pattern_occurrence_ticker_observed",
            "pattern_occurrence",
            ["ticker", "observed_on"],
            unique=False,
        )
    if not _has_index("impact_stat", "ix_impact_stat_type_period"):
        op.create_index(
            "ix_impact_stat_type_period",
            "impact_stat",
            ["announcement_type", "period_key"],
            unique=False,
        )
    if not _has_index("outcome_tracking", "ix_outcome_tracking_source_resolved"):
        op.create_index(
            "ix_outcome_tracking_source_resolved",
            "outcome_tracking",
            ["source_agent", "resolved_at"],
            unique=False,
        )
    if not _has_index("archive_run", "ix_archive_run_type_period"):
        op.create_index(
            "ix_archive_run_type_period",
            "archive_run",
            ["run_type", "period_key"],
            unique=False,
        )


def downgrade() -> None:
    if _has_index("archive_run", "ix_archive_run_type_period"):
        op.drop_index("ix_archive_run_type_period", table_name="archive_run")
    if _has_index("outcome_tracking", "ix_outcome_tracking_source_resolved"):
        op.drop_index("ix_outcome_tracking_source_resolved", table_name="outcome_tracking")
    if _has_index("impact_stat", "ix_impact_stat_type_period"):
        op.drop_index("ix_impact_stat_type_period", table_name="impact_stat")
    if _has_index("pattern_occurrence", "ix_pattern_occurrence_ticker_observed"):
        op.drop_index("ix_pattern_occurrence_ticker_observed", table_name="pattern_occurrence")
    if _has_index("pattern", "ix_pattern_active_status_updated"):
        op.drop_index("ix_pattern_active_status_updated", table_name="pattern")
