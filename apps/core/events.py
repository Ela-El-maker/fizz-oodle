from __future__ import annotations

import json
from uuid import uuid4
from datetime import datetime, timezone

from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ResponseError

from apps.core.config import get_settings
from apps.core.event_schemas import (
    AnalystReportGeneratedV1,
    ArchivistPatternsUpdatedV1,
    OpsHealingAppliedV1,
    RunCommandV1,
    RunEventV1,
)
from apps.core.logger import get_logger

logger = get_logger(__name__)

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=False,
            max_connections=20,
        )
    return _pool


def _get_client() -> Redis:
    return Redis(connection_pool=_get_pool())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_stream_values(payload: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in payload.items():
        if isinstance(v, str):
            out[k] = v
        else:
            # Serialize non-string values through JSON to preserve bool/null types.
            out[k] = json.dumps(v)
    return out


def _from_stream_values(values: dict) -> dict:
    parsed: dict = {}
    for raw_k, raw_v in values.items():
        k = raw_k.decode("utf-8") if isinstance(raw_k, bytes) else str(raw_k)
        v = raw_v.decode("utf-8") if isinstance(raw_v, bytes) else str(raw_v)
        try:
            parsed[k] = json.loads(v)
        except Exception:
            parsed[k] = v
    return parsed


async def publish_event(stream: str, payload: dict) -> str:
    settings = get_settings()
    values = _to_stream_values(payload)
    client = _get_client()
    event_id = await client.xadd(stream, values, maxlen=settings.REDIS_STREAM_MAXLEN, approximate=True)
    if isinstance(event_id, bytes):
        return event_id.decode("utf-8")
    return str(event_id)


async def publish_run_command(
    agent_name: str,
    run_id: str | None = None,
    trigger_type: str | None = None,
    schedule_key: str | None = None,
    requested_by: str | None = None,
    scheduled_for: str | None = None,
    report_type: str | None = None,
    run_type: str | None = None,
    period_key: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
) -> dict:
    settings = get_settings()
    resolved_run_id = run_id or str(uuid4())
    raw_payload = {
        "schema": "RunCommandV1",
        "command_id": str(uuid4()),
        "run_id": resolved_run_id,
        "agent_name": agent_name,
        "trigger_type": trigger_type,
        "schedule_key": schedule_key,
        "requested_by": requested_by,
        "scheduled_for": scheduled_for,
        "report_type": report_type,
        "run_type": run_type,
        "period_key": period_key,
        "force_send": force_send,
        "email_recipients_override": email_recipients_override,
        "requested_at": _utc_now_iso(),
    }
    payload = RunCommandV1.model_validate(raw_payload).model_dump(mode="json", by_alias=True)
    event_id = await publish_event(settings.REDIS_STREAM_COMMANDS, payload)
    payload["event_id"] = event_id
    return payload


async def publish_run_event(
    *,
    run_id: str,
    agent_name: str,
    status: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    metrics: dict | None = None,
    error_message: str | None = None,
    records_processed: int | None = None,
    records_new: int | None = None,
    errors_count: int | None = None,
) -> dict:
    settings = get_settings()
    raw_payload = {
        "schema": "RunEventV1",
        "run_id": run_id,
        "agent_name": agent_name,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "metrics": metrics or {},
        "error_message": error_message,
        "records_processed": records_processed,
        "records_new": records_new,
        "errors_count": errors_count,
        "event_at": _utc_now_iso(),
    }
    payload = RunEventV1.model_validate(raw_payload).model_dump(mode="json", by_alias=True)
    event_id = await publish_event(settings.REDIS_STREAM_RUN_EVENTS, payload)
    payload["event_id"] = event_id
    return payload


async def publish_analyst_report_generated(payload: dict) -> dict:
    settings = get_settings()
    validated = AnalystReportGeneratedV1.model_validate(payload).model_dump(mode="json", by_alias=True)
    event_id = await publish_event(settings.REDIS_STREAM_ANALYST_REPORTS, validated)
    validated["event_id"] = event_id
    return validated


async def publish_archivist_patterns_updated(payload: dict) -> dict:
    settings = get_settings()
    validated = ArchivistPatternsUpdatedV1.model_validate(payload).model_dump(mode="json", by_alias=True)
    event_id = await publish_event(settings.REDIS_STREAM_ARCHIVIST_PATTERNS, validated)
    validated["event_id"] = event_id
    return validated


async def publish_ops_healing_applied(payload: dict) -> dict:
    settings = get_settings()
    validated = OpsHealingAppliedV1.model_validate(payload).model_dump(mode="json", by_alias=True)
    event_id = await publish_event(settings.REDIS_STREAM_SYSTEM_EVENTS, validated)
    validated["event_id"] = event_id
    return validated


async def iter_stream(stream: str, *, last_id: str = "$", block_ms: int = 5000, count: int = 50):
    client = _get_client()
    cursor = last_id
    try:
        while True:
            data = await client.xread({stream: cursor}, block=block_ms, count=count)
            if not data:
                yield None, None, None
                continue
            for stream_name, entries in data:
                s_name = stream_name.decode("utf-8") if isinstance(stream_name, bytes) else str(stream_name)
                for msg_id, values in entries:
                    msg = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id)
                    cursor = msg
                    yield s_name, msg, _from_stream_values(values)
    finally:
        await client.aclose()


async def iter_stream_group(
    stream: str,
    *,
    group: str,
    consumer: str,
    block_ms: int = 5000,
    count: int = 50,
):
    client = _get_client()
    try:
        try:
            # "$" avoids replaying historical backlog on first group creation.
            await client.xgroup_create(stream, group, id="$", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

        while True:
            data = await client.xreadgroup(groupname=group, consumername=consumer, streams={stream: ">"}, block=block_ms, count=count)
            if not data:
                yield None, None, None
                continue
            for stream_name, entries in data:
                s_name = stream_name.decode("utf-8") if isinstance(stream_name, bytes) else str(stream_name)
                for msg_id, values in entries:
                    msg = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id)
                    yield s_name, msg, _from_stream_values(values)
    finally:
        await client.aclose()


async def ack_stream_group(stream: str, *, group: str, message_id: str) -> int:
    client = _get_client()
    return int(await client.xack(stream, group, message_id))
