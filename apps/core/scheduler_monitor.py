from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from celery.schedules import crontab
import httpx
import yaml
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.config import get_settings
from apps.core.models import (
    AgentRun,
    EmailValidationRun,
    RunCommand,
    SchedulerDispatch,
    SchedulerTimelineEvent,
)

settings = get_settings()
EAT_TZ = ZoneInfo("Africa/Nairobi")

AGENT_FROM_TASK = {
    "agent_briefing.run": "briefing",
    "agent_announcements.run": "announcements",
    "agent_sentiment.run": "sentiment",
    "agent_analyst.run": "analyst",
    "agent_archivist.run": "archivist",
    "agent_narrator.run": "narrator",
}

AGENT_LABELS = {
    "briefing": "Agent A (Prices)",
    "announcements": "Agent B (Announcements)",
    "sentiment": "Agent C (Sentiment)",
    "analyst": "Agent D (Analyst)",
    "archivist": "Agent E (Patterns)",
    "narrator": "Agent F (Narrator)",
    "email_validation": "Email Dispatch",
}

LLM_AGENT_SET = {"briefing", "announcements", "sentiment", "analyst", "narrator"}
EMAIL_VALIDATION_WINDOW_AGENTS = {
    "daily": ["briefing", "announcements", "analyst"],
    "weekly": ["sentiment", "archivist", "analyst"],
}


@lru_cache(maxsize=1)
def _load_dependencies() -> dict[str, Any]:
    dep_path = Path(getattr(settings, "AGENT_DEPENDENCIES_CONFIG_PATH", "config/agent_dependencies.yml"))
    if not dep_path.is_absolute():
        dep_path = (Path(__file__).resolve().parents[2] / dep_path).resolve()
    if not dep_path.exists():
        return {
            "agents": {
                "briefing": {"key": "A", "depends_on": []},
                "announcements": {"key": "B", "depends_on": []},
                "sentiment": {"key": "C", "depends_on": []},
                "analyst": {"key": "D", "depends_on": ["briefing", "announcements", "sentiment"]},
                "archivist": {"key": "E", "depends_on": ["analyst"]},
                "narrator": {"key": "F", "depends_on": ["analyst", "archivist"]},
                "email_validation": {"key": "EMAIL", "depends_on": ["narrator"]},
            }
        }
    payload = yaml.safe_load(dep_path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _parse_utc_cron(expr: str) -> crontab:
    minute, hour, day_of_month, month_of_year, day_of_week = expr.strip().split()
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _fmt_eat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(EAT_TZ).isoformat()


def _duration_seconds(started_at: datetime | None, finished_at: datetime | None, now_utc: datetime) -> float | None:
    if not started_at:
        return None
    if finished_at and finished_at >= started_at:
        return max(0.0, (finished_at - started_at).total_seconds())
    return max(0.0, (now_utc - started_at).total_seconds())


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = (len(sorted_values) - 1) * p
    lo = int(idx)
    hi = min(len(sorted_values) - 1, lo + 1)
    frac = idx - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


async def _service_get_json(
    base_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    use_internal_key: bool = False,
) -> dict[str, Any]:
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    headers = {
        ("X-Internal-Api-Key" if use_internal_key else "X-API-Key"): settings.INTERNAL_API_KEY if use_internal_key else settings.API_KEY,
    }
    timeout = max(3, int(getattr(settings, "NARRATOR_TIMEOUT_SECONDS", 20)))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{base_url.rstrip('/')}{path}", params=clean_params, headers=headers)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def _get_scheduler_internal(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        return await _service_get_json(
            "http://scheduler-service:8010",
            path,
            params=params,
            use_internal_key=True,
        )
    except Exception:
        return None


async def _check_health(base_url: str) -> bool:
    try:
        payload = await _service_get_json(base_url, "/internal/health", use_internal_key=True)
        status = str(payload.get("status") or "").lower()
        return status in {"ok", "success", "healthy"}
    except Exception:
        return False


def _latest_by_agent(runs: list[AgentRun]) -> dict[str, AgentRun]:
    out: dict[str, AgentRun] = {}
    for row in runs:
        if row.agent_name not in out:
            out[row.agent_name] = row
    return out


def _runtime_stats_by_agent(runs: list[AgentRun], now_utc: datetime) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = {}
    for row in runs:
        if row.status not in {"success", "partial", "fail"}:
            continue
        dur = _duration_seconds(row.started_at, row.finished_at, now_utc)
        if dur is None:
            continue
        grouped.setdefault(row.agent_name, []).append(float(dur))

    stats: dict[str, dict[str, float]] = {}
    for agent_name, samples in grouped.items():
        stats[agent_name] = {
            "p50": float(median(samples)),
            "p95": _percentile(samples, 0.95),
        }
    return stats


def _agent_recent_success(row: AgentRun | None, now_utc: datetime, minutes: int = 180) -> bool:
    if row is None:
        return False
    if row.status not in {"success", "partial"}:
        return False
    ts = row.finished_at or row.started_at
    if ts is None:
        return False
    return ts >= now_utc - timedelta(minutes=minutes)


def _forecast_schedule_runs(schedules: list[dict[str, Any]], now_utc: datetime, hours: int) -> list[dict[str, Any]]:
    horizon = now_utc + timedelta(hours=hours)
    items: list[dict[str, Any]] = []

    for schedule in schedules:
        utc_cron = str(schedule.get("utc_cron") or "").strip()
        if not utc_cron:
            continue
        try:
            cron = _parse_utc_cron(utc_cron)
        except Exception:
            continue

        cursor = now_utc
        generated = 0
        while generated < 96:
            try:
                delta = cron.remaining_estimate(cursor)
                next_dt = cursor + delta
            except Exception:
                break
            if next_dt > horizon:
                break
            if next_dt <= now_utc:
                cursor = cursor + timedelta(minutes=1)
                continue

            items.append(
                {
                    "schedule_key": schedule.get("schedule_key"),
                    "task_name": schedule.get("task_name"),
                    "agent_name": AGENT_FROM_TASK.get(str(schedule.get("task_name") or ""), "email_validation"),
                    "trigger_type": "scheduled",
                    "next_run_at_utc": next_dt.isoformat(),
                    "next_run_at_eat": _fmt_eat(next_dt),
                    "timezone": schedule.get("timezone") or "Africa/Nairobi",
                    "notes": schedule.get("notes"),
                }
            )
            generated += 1
            cursor = next_dt + timedelta(seconds=1)

    items.sort(key=lambda item: item.get("next_run_at_utc") or "")
    return items


def _impact_chain(failed_agent: str, dependencies: dict[str, Any]) -> list[str]:
    agents = dependencies.get("agents") if isinstance(dependencies, dict) else {}
    if not isinstance(agents, dict):
        return []
    reverse: dict[str, list[str]] = {}
    for agent_name, config in agents.items():
        depends_on = config.get("depends_on") if isinstance(config, dict) else []
        for dep in depends_on or []:
            reverse.setdefault(dep, []).append(agent_name)

    impacted: list[str] = []
    queue = [failed_agent]
    seen = {failed_agent}
    while queue:
        current = queue.pop(0)
        for nxt in reverse.get(current, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            impacted.append(nxt)
            queue.append(nxt)
    return impacted


async def build_scheduler_snapshot(
    session: AsyncSession,
    *,
    hours: int = 24,
    events_limit: int = 50,
    pipeline_window_minutes: int = 120,
    failed_agent: str | None = None,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    safe_hours = max(1, min(72, int(hours)))
    safe_events = max(10, min(200, int(events_limit)))
    safe_window = max(30, min(360, int(pipeline_window_minutes)))

    schedules_payload, scheduler_state, health_checks = await asyncio.gather(
        _get_scheduler_internal("/internal/schedules"),
        _get_scheduler_internal("/internal/state"),
        asyncio.gather(
            _check_health(settings.AGENT_A_SERVICE_URL),
            _check_health(settings.AGENT_B_SERVICE_URL),
            _check_health(settings.AGENT_C_SERVICE_URL),
            _check_health(settings.AGENT_D_SERVICE_URL),
            _check_health(settings.AGENT_E_SERVICE_URL),
            _check_health(settings.AGENT_F_SERVICE_URL),
        ),
    )

    runs_rows = (
        await session.execute(select(AgentRun).order_by(desc(AgentRun.started_at)).limit(600))
    ).scalars().all()
    run_commands_rows = (
        await session.execute(select(RunCommand).order_by(desc(RunCommand.requested_at)).limit(600))
    ).scalars().all()
    dispatch_rows = (
        await session.execute(select(SchedulerDispatch).order_by(desc(SchedulerDispatch.dispatched_at)).limit(600))
    ).scalars().all()
    timeline_rows = (
        await session.execute(select(SchedulerTimelineEvent).order_by(desc(SchedulerTimelineEvent.event_time)).limit(600))
    ).scalars().all()
    email_runs_rows = (
        await session.execute(select(EmailValidationRun).order_by(desc(EmailValidationRun.started_at)).limit(40))
    ).scalars().all()

    latest_by_agent = _latest_by_agent(runs_rows)
    runtime_stats = _runtime_stats_by_agent(runs_rows, now_utc)
    dependencies = _load_dependencies()
    dep_agents = dependencies.get("agents") if isinstance(dependencies, dict) else {}
    dep_agents = dep_agents if isinstance(dep_agents, dict) else {}

    schedules = schedules_payload.get("items", []) if isinstance(schedules_payload, dict) else []
    schedules = schedules if isinstance(schedules, list) else []
    schedule_by_key: dict[str, dict[str, Any]] = {}
    for row in schedules:
        if isinstance(row, dict):
            key = str(row.get("schedule_key") or "").strip()
            if key:
                schedule_by_key[key] = row
    forecast = _forecast_schedule_runs(schedules, now_utc, safe_hours)

    command_by_run: dict[str, RunCommand] = {}
    for row in run_commands_rows:
        key = str(row.run_id)
        if key not in command_by_run:
            command_by_run[key] = row

    completed_runs = [row for row in runs_rows if row.status in {"success", "partial", "fail"}]
    past_items: list[dict[str, Any]] = []
    for row in completed_runs[:80]:
        dur = _duration_seconds(row.started_at, row.finished_at, now_utc)
        cmd = command_by_run.get(str(row.run_id))
        past_items.append(
            {
                "run_id": str(row.run_id),
                "agent_name": row.agent_name,
                "agent_label": AGENT_LABELS.get(row.agent_name, row.agent_name),
                "status": row.status,
                "status_reason": (row.metrics or {}).get("status_reason") or row.error_message,
                "trigger_type": cmd.trigger_type if cmd else "unknown",
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "duration_seconds": int(dur) if dur is not None else None,
                "email_sent": bool((row.metrics or {}).get("email_sent")),
                "llm_used": bool((row.metrics or {}).get("llm_used")),
            }
        )

    running_rows = [row for row in runs_rows if row.status == "running"]
    queued_commands = [row for row in run_commands_rows if row.lifecycle_status == "queued"]

    blocked_rows: list[dict[str, Any]] = []
    for cmd in queued_commands[:120]:
        deps = dep_agents.get(cmd.agent_name, {}).get("depends_on", []) if isinstance(dep_agents.get(cmd.agent_name), dict) else []
        unmet = [dep for dep in deps if not _agent_recent_success(latest_by_agent.get(dep), now_utc, minutes=180)]
        if unmet:
            blocked_rows.append(
                {
                    "run_id": str(cmd.run_id),
                    "agent_name": cmd.agent_name,
                    "agent_label": AGENT_LABELS.get(cmd.agent_name, cmd.agent_name),
                    "waiting_for": unmet,
                    "requested_at": cmd.requested_at.isoformat() if cmd.requested_at else None,
                    "trigger_type": cmd.trigger_type,
                }
            )

    present_running = [
        {
            "run_id": str(row.run_id),
            "agent_name": row.agent_name,
            "agent_label": AGENT_LABELS.get(row.agent_name, row.agent_name),
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "status": row.status,
            "status_reason": (row.metrics or {}).get("status_reason") or row.error_message,
            "llm_used": bool((row.metrics or {}).get("llm_used")) or row.agent_name in LLM_AGENT_SET,
        }
        for row in running_rows[:80]
    ]

    present_queued = [
        {
            "command_id": str(row.command_id),
            "run_id": str(row.run_id),
            "agent_name": row.agent_name,
            "agent_label": AGENT_LABELS.get(row.agent_name, row.agent_name),
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "trigger_type": row.trigger_type,
            "requested_by": row.requested_by,
            "schedule_key": row.schedule_key,
        }
        for row in queued_commands[:120]
    ]

    future_items: list[dict[str, Any]] = []
    for item in forecast[:240]:
        agent_name = item.get("agent_name") or "unknown"
        stats = runtime_stats.get(agent_name, {"p50": 30.0, "p95": 90.0})
        next_utc = _coerce_dt(item.get("next_run_at_utc"))
        future_items.append(
            {
                **item,
                "predicted_duration_p50_seconds": round(float(stats.get("p50") or 30.0), 2),
                "predicted_duration_p95_seconds": round(float(stats.get("p95") or 90.0), 2),
                "predicted_complete_p50_utc": (
                    (next_utc + timedelta(seconds=float(stats.get("p50") or 30.0))).isoformat() if next_utc else None
                ),
                "predicted_complete_p95_utc": (
                    (next_utc + timedelta(seconds=float(stats.get("p95") or 90.0))).isoformat() if next_utc else None
                ),
                "llm_interaction": agent_name in LLM_AGENT_SET,
            }
        )

    next_run = _coerce_dt(future_items[0].get("next_run_at_utc")) if future_items else None
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    key_order = ["briefing", "announcements", "sentiment", "analyst", "archivist", "narrator", "email_validation"]

    for agent in key_order:
        latest = latest_by_agent.get(agent)
        status = "idle"
        if latest:
            if latest.status == "fail":
                status = "error"
            elif latest.status == "running":
                status = "active"
            elif _agent_recent_success(latest, now_utc, minutes=safe_window):
                status = "active"
        nodes.append(
            {
                "id": dep_agents.get(agent, {}).get("key", agent.upper()),
                "agent_name": agent,
                "label": AGENT_LABELS.get(agent, agent),
                "status": status,
            }
        )

    for agent_name, config in dep_agents.items():
        depends = config.get("depends_on") if isinstance(config, dict) else []
        if not depends:
            continue
        for dep in depends:
            source = dep_agents.get(dep, {}).get("key", dep.upper())
            target = config.get("key", agent_name.upper())
            source_ok = _agent_recent_success(latest_by_agent.get(dep), now_utc, minutes=safe_window)
            target_recent = _agent_recent_success(latest_by_agent.get(agent_name), now_utc, minutes=safe_window)
            if source_ok and target_recent:
                state = "active"
            elif source_ok:
                state = "idle"
            else:
                state = "blocked"
            links.append({"from": source, "to": target, "state": state})

    buckets: list[str] = []
    for i in range(safe_hours):
        bucket_start = now_utc - timedelta(hours=safe_hours - i)
        buckets.append(bucket_start.isoformat())

    heatmap_rows: list[dict[str, Any]] = []
    for agent in key_order:
        cells = [0] * safe_hours
        for run in runs_rows:
            if run.agent_name != agent or not run.started_at:
                continue
            delta_hours = int((now_utc - run.started_at).total_seconds() // 3600)
            if 0 <= delta_hours < safe_hours:
                idx = safe_hours - delta_hours - 1
                cells[idx] += 1
        heatmap_rows.append(
            {
                "agent_name": agent,
                "label": AGENT_LABELS.get(agent, agent),
                "cells": cells,
            }
        )

    event_items: list[dict[str, Any]] = [
        {
            "event_time": row.event_time.isoformat() if row.event_time else None,
            "event_type": row.event_type,
            "severity": row.severity,
            "source": row.source,
            "agent_name": row.agent_name,
            "run_id": str(row.run_id) if row.run_id else None,
            "schedule_key": row.schedule_key,
            "message": row.message,
            "details": row.details or {},
        }
        for row in timeline_rows[: safe_events * 2]
    ]

    if len(event_items) < safe_events:
        for row in runs_rows[: safe_events * 2]:
            event_time = row.finished_at or row.started_at
            if not event_time:
                continue
            event_items.append(
                {
                    "event_time": event_time.isoformat(),
                    "event_type": f"run_{row.status}",
                    "severity": "error" if row.status == "fail" else "warn" if row.status == "partial" else "info",
                    "source": "run_ledger",
                    "agent_name": row.agent_name,
                    "run_id": str(row.run_id),
                    "schedule_key": None,
                    "message": f"{AGENT_LABELS.get(row.agent_name, row.agent_name)} {row.status}",
                    "details": {},
                }
            )

    event_items = sorted(
        event_items,
        key=lambda item: _coerce_dt(item.get("event_time")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:safe_events]

    dispatch_accept = sum(1 for row in dispatch_rows[:300] if row.dispatch_status == "accepted")
    dispatch_fail = sum(1 for row in dispatch_rows[:300] if row.dispatch_status == "failed")
    dispatch_skip = sum(1 for row in dispatch_rows[:300] if row.dispatch_status == "skipped")

    email_sent_events = 0
    for row in completed_runs[:300]:
        if bool((row.metrics or {}).get("email_sent")):
            email_sent_events += 1

    email_failures = sum(1 for row in email_runs_rows[:20] if row.status == "fail")
    email_latest = email_runs_rows[0] if email_runs_rows else None

    email_dispatch_items: list[dict[str, Any]] = []
    for schedule_meta in schedules:
        if not isinstance(schedule_meta, dict):
            continue
        if str(schedule_meta.get("task_name") or "") != "ops.email_validation.run":
            continue
        schedule_key = str(schedule_meta.get("schedule_key") or "")
        task_kwargs = schedule_meta.get("task_kwargs")
        task_kwargs = task_kwargs if isinstance(task_kwargs, dict) else {}
        window = str(task_kwargs.get("window") or ("weekly" if "weekly" in schedule_key else "daily")).strip().lower()
        agents = EMAIL_VALIDATION_WINDOW_AGENTS.get(window, [])
        email_dispatch_items.append(
            {
                "schedule_key": schedule_key or None,
                "window": window,
                "next_run_at_utc": schedule_meta.get("next_run_at_utc"),
                "next_run_at_eat": schedule_meta.get("next_run_at_eat"),
                "agents": agents,
            }
        )

    email_dispatch_items = sorted(
        email_dispatch_items,
        key=lambda row: str(row.get("next_run_at_utc") or ""),
    )

    next_email_dispatch_dt = _coerce_dt(email_dispatch_items[0].get("next_run_at_utc")) if email_dispatch_items else None

    next_email_by_agent_map: dict[str, dict[str, Any]] = {}
    for dispatch in email_dispatch_items:
        for agent in dispatch.get("agents") or []:
            if agent in next_email_by_agent_map:
                continue
            next_email_by_agent_map[agent] = {
                "agent_name": agent,
                "agent_label": AGENT_LABELS.get(agent, agent),
                "window": dispatch.get("window"),
                "schedule_key": dispatch.get("schedule_key"),
                "next_run_at_utc": dispatch.get("next_run_at_utc"),
                "next_run_at_eat": dispatch.get("next_run_at_eat"),
            }

    next_email_by_agent = sorted(
        list(next_email_by_agent_map.values()),
        key=lambda row: str(row.get("next_run_at_utc") or ""),
    )

    scheduler_status = "ok" if isinstance(scheduler_state, dict) and scheduler_state.get("status") == "ok" else "degraded"
    loop_interval = int((scheduler_state or {}).get("loop_interval_seconds") or 10)
    last_tick = _coerce_dt((scheduler_state or {}).get("last_tick_at"))

    active_runs = len(present_running)
    queued_jobs = len(present_queued)
    blocked_jobs = len(blocked_rows)
    llm_active = len([item for item in present_running if item.get("llm_used")])

    health_ok = sum(1 for ok in health_checks if ok)
    agent_connectivity = {
        "status": "ok" if health_ok == len(health_checks) else "degraded",
        "healthy_agents": health_ok,
        "total_agents": len(health_checks),
    }

    latency_samples = [
        _duration_seconds(row.started_at, row.finished_at, now_utc)
        for row in completed_runs[:300]
        if row.started_at is not None
    ]
    latency_values = [float(v) for v in latency_samples if v is not None]
    p50 = float(median(latency_values)) if latency_values else 0.0
    p95 = _percentile(latency_values, 0.95) if latency_values else 0.0

    data_freshness_minutes = None
    if completed_runs:
        latest_complete = completed_runs[0].finished_at or completed_runs[0].started_at
        if latest_complete:
            data_freshness_minutes = int(max(0.0, (now_utc - latest_complete).total_seconds() / 60.0))

    health = {
        "data_freshness": {
            "status": "ok" if data_freshness_minutes is not None and data_freshness_minutes <= 30 else "stale",
            "minutes_since_last_success": data_freshness_minutes,
        },
        "agent_connectivity": agent_connectivity,
        "pipeline_latency": {
            "status": "ok" if p95 <= 60 else "degraded",
            "p50_seconds": round(p50, 2),
            "p95_seconds": round(p95, 2),
        },
        "scheduler_dispatch": {
            "status": "ok" if dispatch_fail == 0 else "degraded",
            "accepted": dispatch_accept,
            "failed": dispatch_fail,
            "skipped": dispatch_skip,
        },
        "email_dispatch": {
            "status": "ok" if email_failures == 0 else "degraded",
            "sent_count": email_sent_events,
            "recent_failures": email_failures,
        },
    }

    failed = (failed_agent or "").strip().lower()
    impact_agents = _impact_chain(failed, dependencies) if failed else []
    impact_items = []
    for agent in impact_agents:
        next_item = next((item for item in future_items if item.get("agent_name") == agent), None)
        impact_items.append(
            {
                "agent_name": agent,
                "label": AGENT_LABELS.get(agent, agent),
                "next_run_at_utc": next_item.get("next_run_at_utc") if next_item else None,
                "next_run_at_eat": next_item.get("next_run_at_eat") if next_item else None,
                "estimated_slippage_seconds": int((runtime_stats.get(failed, {}).get("p95") or 90.0)),
            }
        )

    today_eat = now_utc.astimezone(EAT_TZ).date()
    daily_action_counts: dict[str, dict[str, int]] = {}
    for row in timeline_rows:
        event_time = row.event_time
        if event_time is None:
            continue
        event_dt = event_time if event_time.tzinfo else event_time.replace(tzinfo=timezone.utc)
        if event_dt.astimezone(EAT_TZ).date() != today_eat:
            continue
        agent_name = row.agent_name or "unknown"
        event_type = str(row.event_type or "event")
        agent_actions = daily_action_counts.setdefault(agent_name, {})
        agent_actions[event_type] = int(agent_actions.get(event_type, 0) + 1)

    daily_streak_items: list[dict[str, Any]] = []
    for agent in key_order:
        agent_rows = []
        for run in runs_rows:
            if run.agent_name != agent:
                continue
            stamp = run.started_at or run.finished_at
            if stamp is None:
                continue
            stamp_dt = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            if stamp_dt.astimezone(EAT_TZ).date() != today_eat:
                continue
            agent_rows.append(run)

        success_count = len([r for r in agent_rows if r.status == "success"])
        partial_count = len([r for r in agent_rows if r.status == "partial"])
        fail_count = len([r for r in agent_rows if r.status == "fail"])
        running_count = len([r for r in agent_rows if r.status == "running"])
        email_sent_count = 0
        for r in agent_rows:
            metrics = r.metrics or {}
            if bool(metrics.get("email_sent")) or bool(metrics.get("digest_sent")):
                email_sent_count += 1
        last_run_at = None
        if agent_rows:
            timestamps = [((r.finished_at or r.started_at) if (r.finished_at or r.started_at) else None) for r in agent_rows]
            timestamps = [ts for ts in timestamps if ts is not None]
            if timestamps:
                latest_ts = max(
                    ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                    for ts in timestamps
                )
                last_run_at = latest_ts.isoformat()

        action_counts = daily_action_counts.get(agent, {})
        top_actions = sorted(action_counts.items(), key=lambda item: item[1], reverse=True)[:4]
        daily_streak_items.append(
            {
                "agent_name": agent,
                "agent_label": AGENT_LABELS.get(agent, agent),
                "runs_today": len(agent_rows),
                "success_today": success_count,
                "partial_today": partial_count,
                "fail_today": fail_count,
                "running_now": running_count,
                "email_sent_today": email_sent_count,
                "last_run_at_utc": last_run_at,
                "last_run_at_eat": _fmt_eat(_coerce_dt(last_run_at)),
                "actions_today": [
                    {"event_type": event_type, "count": count}
                    for event_type, count in top_actions
                ],
            }
        )

    snapshot = {
        "generated_at": now_utc.isoformat(),
        "time": {
            "now_utc": now_utc.isoformat(),
            "now_eat": _fmt_eat(now_utc),
        },
        "status": {
            "scheduler_status": scheduler_status,
            "last_tick_at": last_tick.isoformat() if last_tick else None,
            "last_tick_at_eat": _fmt_eat(last_tick),
            "loop_interval_seconds": loop_interval,
            "schedules_loaded": len(schedules),
        },
        "metrics": {
            "active_runs": active_runs,
            "queued_jobs": queued_jobs,
            "blocked_jobs": blocked_jobs,
            "next_run_eta_seconds": int(max(0.0, (next_run - now_utc).total_seconds())) if next_run else None,
            "next_email_eta_seconds": int(max(0.0, (next_email_dispatch_dt - now_utc).total_seconds())) if next_email_dispatch_dt else None,
            "llm_active_jobs": llm_active,
        },
        "past": {
            "items": past_items[:50],
            "limit": 50,
        },
        "present": {
            "running": present_running,
            "queued": present_queued,
            "blocked": blocked_rows,
        },
        "future": {
            "hours": safe_hours,
            "items": future_items,
        },
        "pipeline": {
            "window_minutes": safe_window,
            "nodes": nodes,
            "links": links,
        },
        "heatmap": {
            "hours": safe_hours,
            "buckets": buckets,
            "rows": heatmap_rows,
        },
        "email": {
            "next_scheduled_at_utc": next_email_dispatch_dt.isoformat() if next_email_dispatch_dt else None,
            "next_scheduled_at_eat": _fmt_eat(next_email_dispatch_dt),
            "latest_validation_window": email_latest.window if email_latest else None,
            "latest_validation_status": email_latest.status if email_latest else None,
            "latest_validation_at": (
                (email_latest.finished_at or email_latest.started_at).isoformat()
                if email_latest and (email_latest.finished_at or email_latest.started_at)
                else None
            ),
            "sent_count_recent": email_sent_events,
            "failure_count_recent": email_failures,
            "next_validation_dispatches": email_dispatch_items,
            "next_email_by_agent": next_email_by_agent,
        },
        "events": {
            "items": event_items,
            "limit": safe_events,
        },
        "impact": {
            "failed_agent": failed or None,
            "items": impact_items,
        },
        "health": health,
        "daily_streak": {
            "date_eat": today_eat.isoformat(),
            "items": daily_streak_items,
        },
    }
    return snapshot


async def get_scheduler_status(session: AsyncSession) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(session, hours=24, events_limit=20)
    return {
        "generated_at": snapshot["generated_at"],
        "status": snapshot["status"],
        "metrics": snapshot["metrics"],
    }


async def get_scheduler_active(session: AsyncSession) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(session, hours=24, events_limit=20)
    return snapshot["present"]


async def get_scheduler_upcoming(session: AsyncSession, *, hours: int = 24) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(session, hours=hours, events_limit=20)
    return snapshot["future"]


async def get_scheduler_history(session: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(session, hours=24, events_limit=20)
    safe_limit = max(1, min(int(limit), 200))
    return {"items": snapshot["past"]["items"][:safe_limit], "limit": safe_limit}


async def get_scheduler_pipeline(session: AsyncSession, *, window_minutes: int = 120) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(
        session,
        hours=24,
        events_limit=20,
        pipeline_window_minutes=window_minutes,
    )
    return snapshot["pipeline"]


async def get_scheduler_email(session: AsyncSession) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(session, hours=24, events_limit=20)
    return snapshot["email"]


async def get_scheduler_events(session: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    snapshot = await build_scheduler_snapshot(session, hours=24, events_limit=max(50, safe_limit))
    return {"items": snapshot["events"]["items"][:safe_limit], "limit": safe_limit}


async def get_scheduler_heatmap(session: AsyncSession, *, hours: int = 24) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(session, hours=hours, events_limit=20)
    return snapshot["heatmap"]


async def get_scheduler_impact(session: AsyncSession, *, failed_agent: str) -> dict[str, Any]:
    snapshot = await build_scheduler_snapshot(session, hours=24, events_limit=20, failed_agent=failed_agent)
    return snapshot["impact"]
