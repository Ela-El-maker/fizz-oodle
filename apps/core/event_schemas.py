from __future__ import annotations

from datetime import datetime, date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _EventBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class RunCommandV1(_EventBase):
    schema_name: Literal["RunCommandV1"] = Field("RunCommandV1", alias="schema")
    command_id: str
    run_id: str | None = None
    agent_name: str
    trigger_type: str | None = None
    schedule_key: str | None = None
    requested_by: str | None = None
    scheduled_for: datetime | None = None
    report_type: str | None = None
    run_type: str | None = None
    period_key: str | None = None
    force_send: bool | None = None
    email_recipients_override: str | None = None
    requested_at: datetime


class RunEventV1(_EventBase):
    schema_name: Literal["RunEventV1"] = Field("RunEventV1", alias="schema")
    run_id: str
    agent_name: str
    status: Literal["running", "success", "partial", "fail"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metrics: dict = Field(default_factory=dict)
    error_message: str | None = None
    records_processed: int | None = None
    records_new: int | None = None
    errors_count: int | None = None
    event_at: datetime


class AnalystReportGeneratedV1(_EventBase):
    schema_name: Literal["AnalystReportGeneratedV1"] = Field("AnalystReportGeneratedV1", alias="schema")
    report_id: str
    report_type: Literal["daily", "weekly"]
    period_key: date
    degraded: bool
    generated_at: datetime


class ArchivistPatternsUpdatedV1(_EventBase):
    schema_name: Literal["ArchivistPatternsUpdatedV1"] = Field("ArchivistPatternsUpdatedV1", alias="schema")
    run_type: Literal["weekly", "monthly"]
    period_key: date
    patterns_upserted: int
    impacts_upserted: int
    accuracy_rows_upserted: int
    generated_at: datetime
    degraded: bool


class OpsHealingAppliedV1(_EventBase):
    schema_name: Literal["OpsHealingAppliedV1"] = Field("OpsHealingAppliedV1", alias="schema")
    incident_id: str
    component: str
    failure_type: str
    action: str
    result: str
    auto_applied: bool
    escalated: bool
    occurred_at: datetime
