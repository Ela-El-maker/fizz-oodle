from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import math
from statistics import median
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.config import get_settings
from apps.core.models import ContextFetchJob, EvidencePack

settings = get_settings()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def _minutes_since(value: datetime | None, now_utc: datetime) -> float | None:
    if not value:
        return None
    return max(0.0, (now_utc - value).total_seconds() / 60.0)


def _is_recent_success(run: dict[str, Any] | None, now_utc: datetime, window_minutes: int) -> bool:
    if not run:
        return False
    status = str(run.get("status") or "").lower()
    if status not in {"success", "partial"}:
        return False
    ts = _coerce_dt(run.get("finished_at")) or _coerce_dt(run.get("started_at"))
    if not ts:
        return False
    return ts >= now_utc - timedelta(minutes=window_minutes)


def _is_recent_activity(run: dict[str, Any] | None, now_utc: datetime, window_minutes: int) -> bool:
    if not run:
        return False
    status = str(run.get("status") or "").lower()
    if status == "running":
        started_at = _coerce_dt(run.get("started_at"))
        return bool(started_at and started_at >= now_utc - timedelta(minutes=window_minutes))
    return _is_recent_success(run, now_utc, window_minutes)


def _duration_seconds(run: dict[str, Any], now_utc: datetime) -> float | None:
    started = _coerce_dt(run.get("started_at"))
    if not started:
        return None
    finished = _coerce_dt(run.get("finished_at"))
    if finished and finished >= started:
        return (finished - started).total_seconds()
    if str(run.get("status") or "").lower() == "running":
        return max(0.0, (now_utc - started).total_seconds())
    return None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * p
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_values[lo])
    frac = rank - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


async def _service_get_json(
    base_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    use_internal_key: bool = False,
) -> dict[str, Any]:
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    timeout = max(3, int(settings.NARRATOR_TIMEOUT_SECONDS))
    headers = {
        ("X-Internal-Api-Key" if use_internal_key else "X-API-Key"): settings.INTERNAL_API_KEY if use_internal_key else settings.API_KEY,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{base_url.rstrip('/')}{path}", params=clean_params, headers=headers)
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


async def _run_ledger_get(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return await _service_get_json(settings.RUN_LEDGER_SERVICE_URL, path, params=params)


async def _run_ledger_get_safe(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        return await _run_ledger_get(path, params=params)
    except Exception:
        return None


async def _agent_health_status(base_url: str) -> bool:
    try:
        payload = await _service_get_json(base_url, "/internal/health", use_internal_key=True)
        status = str(payload.get("status") or "").lower()
        return status in {"ok", "healthy", "success"}
    except Exception:
        return False


async def _collect_upstream_latest() -> dict[str, dict[str, Any] | None]:
    mapping = {
        "A": "briefing",
        "B": "announcements",
        "C": "sentiment",
        "D": "analyst",
        "E": "archivist",
    }
    tasks = [
        _run_ledger_get_safe(f"/runs/latest/{agent_name}")
        for agent_name in mapping.values()
    ]
    results = await asyncio.gather(*tasks)
    return {
        key: result
        for (key, _), result in zip(mapping.items(), results, strict=False)
    }


async def _collect_connectivity() -> tuple[int, int]:
    checks = await asyncio.gather(
        _agent_health_status(settings.AGENT_A_SERVICE_URL),
        _agent_health_status(settings.AGENT_B_SERVICE_URL),
        _agent_health_status(settings.AGENT_C_SERVICE_URL),
        _agent_health_status(settings.AGENT_D_SERVICE_URL),
        _agent_health_status(settings.AGENT_E_SERVICE_URL),
        _agent_health_status(settings.RUN_LEDGER_SERVICE_URL),
    )
    healthy = sum(1 for item in checks if item)
    return healthy, len(checks)


def _map_job_status(status: str) -> str:
    normalized = (status or "").lower()
    if normalized in {"running", "queued"}:
        return "processing"
    if normalized == "success":
        return "completed"
    if normalized == "partial":
        return "degraded"
    return "failed"


def _event_level_from_status(status: str) -> str:
    normalized = (status or "").lower()
    if normalized == "fail":
        return "error"
    if normalized == "partial":
        return "warn"
    return "info"


async def build_monitor_snapshot(
    session: AsyncSession,
    *,
    window_minutes: int = 30,
    events_limit: int = 20,
    cycles_limit: int = 5,
) -> dict[str, Any]:
    now_utc = _utc_now()
    safe_window = max(5, min(180, int(window_minutes)))
    safe_events = max(1, min(100, int(events_limit)))
    safe_cycles = max(1, min(20, int(cycles_limit)))

    narrator_runs_payload, upstream_latest, connectivity = await asyncio.gather(
        _run_ledger_get_safe("/runs", params={"agent_name": "narrator", "limit": 50}),
        _collect_upstream_latest(),
        _collect_connectivity(),
    )

    narrator_runs = []
    if narrator_runs_payload and isinstance(narrator_runs_payload.get("items"), list):
        narrator_runs = [item for item in narrator_runs_payload["items"] if isinstance(item, dict)]

    latest_narrator = narrator_runs[0] if narrator_runs else None
    latest_status = str((latest_narrator or {}).get("status") or "").lower()
    narrator_running = latest_status == "running"
    recent_narrator_active = _is_recent_activity(latest_narrator, now_utc, safe_window)

    recent_failures = sum(
        1 for run in narrator_runs[:3]
        if str(run.get("status") or "").lower() == "fail"
    )
    upstream_missing = [
        key for key, run in upstream_latest.items()
        if not _is_recent_success(run, now_utc, safe_window)
    ]

    if narrator_running:
        agent_status = "PROCESSING"
    elif latest_status == "fail" or recent_failures >= 2:
        agent_status = "ERROR"
    elif upstream_missing:
        agent_status = "WAITING_FOR_DATA"
    elif recent_narrator_active:
        agent_status = "ACTIVE"
    else:
        agent_status = "IDLE"

    started_at = _coerce_dt((latest_narrator or {}).get("started_at"))
    completed_durations = [
        _duration_seconds(run, now_utc)
        for run in narrator_runs
        if _duration_seconds(run, now_utc) is not None
        and str(run.get("status") or "").lower() in {"success", "partial", "fail"}
    ]
    completed_durations = [float(item) for item in completed_durations if item is not None]
    p75_duration = _percentile(completed_durations, 0.75) if completed_durations else 60.0

    if narrator_running and started_at:
        elapsed = max(0.0, (now_utc - started_at).total_seconds())
        progress_pct = int(max(5, min(95, (elapsed / max(1.0, p75_duration)) * 100)))
        eta = started_at + timedelta(seconds=p75_duration)
    elif latest_status in {"success", "partial"}:
        progress_pct = 100
        eta = None
    elif latest_status == "fail":
        progress_pct = 0
        eta = None
    else:
        progress_pct = 0
        eta = None

    recent_jobs_stmt = (
        select(ContextFetchJob)
        .order_by(desc(ContextFetchJob.started_at))
        .limit(80)
    )
    recent_jobs_rows = (await session.execute(recent_jobs_stmt)).scalars().all()
    recent_jobs = [
        row for row in recent_jobs_rows
        if (_coerce_dt(row.started_at) or _coerce_dt(row.finished_at) or now_utc) >= now_utc - timedelta(minutes=safe_window)
    ]
    open_recent_jobs = [
        row for row in recent_jobs
        if row.finished_at is None and _coerce_dt(row.started_at) and _coerce_dt(row.started_at) >= now_utc - timedelta(minutes=2)
    ]

    if narrator_running and open_recent_jobs:
        current_task = "Refreshing announcement context"
    elif narrator_running and int(((latest_narrator or {}).get("metrics") or {}).get("announcement_insights_built") or 0) > 0:
        current_task = "Synthesizing announcement intelligence"
    elif narrator_running:
        current_task = "Generating daily market story"
    elif agent_status == "WAITING_FOR_DATA":
        current_task = "Waiting for upstream agents"
    else:
        current_task = "Idle"

    status_reason = (latest_narrator or {}).get("status_reason")

    node_map = {
        "A": {"label": "Agent A (Prices)", "run": upstream_latest.get("A")},
        "B": {"label": "Agent B (Announcements)", "run": upstream_latest.get("B")},
        "C": {"label": "Agent C (Sentiment)", "run": upstream_latest.get("C")},
        "D": {"label": "Agent D (Analyst)", "run": upstream_latest.get("D")},
        "E": {"label": "Agent E (Patterns)", "run": upstream_latest.get("E")},
    }
    nodes: list[dict[str, Any]] = []
    for node_id, meta in node_map.items():
        run = meta["run"]
        status = str((run or {}).get("status") or "").lower()
        if status == "fail":
            node_status = "error"
        elif _is_recent_activity(run, now_utc, safe_window):
            node_status = "active"
        else:
            node_status = "idle"
        nodes.append({"id": node_id, "label": meta["label"], "status": node_status})

    if latest_status == "fail":
        narrator_node_status = "error"
    elif narrator_running or recent_narrator_active:
        narrator_node_status = "active"
    else:
        narrator_node_status = "idle"
    nodes.append({"id": "F", "label": "Agent F (Narrative Engine)", "status": narrator_node_status})

    if latest_status == "fail":
        out_status = "error"
    elif narrator_running or _is_recent_success(latest_narrator, now_utc, safe_window):
        out_status = "active"
    else:
        out_status = "idle"
    nodes.append({"id": "OUT", "label": "Market Story Output", "status": out_status})

    links = []
    for source_id in ("A", "B", "C", "D", "E"):
        source_run = upstream_latest.get(source_id)
        active = _is_recent_success(source_run, now_utc, safe_window) and recent_narrator_active
        links.append({"from": source_id, "to": "F", "state": "active" if active else "idle"})
    links.append({"from": "F", "to": "OUT", "state": "active" if out_status == "active" else "idle"})

    request_items: list[dict[str, Any]] = []
    for run in narrator_runs[:6]:
        run_status = str(run.get("status") or "").lower()
        if run_status not in {"running", "success", "partial", "fail"}:
            continue
        run_time = _coerce_dt(run.get("started_at")) or _coerce_dt(run.get("finished_at"))
        request_items.append(
            {
                "time": run_time.isoformat() if run_time else None,
                "source_agent": "operator",
                "request": "Narrative synthesis cycle",
                "status": "processing" if run_status == "running" else "completed" if run_status in {"success", "partial"} else "failed",
                "inferred": True,
                "evidence": f"run_id:{run.get('run_id')}",
            }
        )

    if narrator_runs:
        anchor = _coerce_dt(narrator_runs[0].get("started_at")) or _coerce_dt(narrator_runs[0].get("finished_at"))
        if anchor:
            request_labels = {
                "A": "Price trend context",
                "B": "Announcement summary",
                "C": "Sentiment aggregation",
                "D": "Analyst context",
                "E": "Pattern context",
            }
            for key, label in request_labels.items():
                run = upstream_latest.get(key)
                if not run:
                    continue
                run_ts = _coerce_dt(run.get("finished_at")) or _coerce_dt(run.get("started_at"))
                if not run_ts:
                    continue
                if abs((run_ts - anchor).total_seconds()) > 600:
                    continue
                run_status = str(run.get("status") or "").lower()
                request_items.append(
                    {
                        "time": run_ts.isoformat(),
                        "source_agent": key,
                        "request": label,
                        "status": "completed" if run_status in {"success", "partial"} else "failed" if run_status == "fail" else "processing",
                        "inferred": True,
                        "evidence": f"run_id:{run.get('run_id')}",
                    }
                )

    for job in recent_jobs[:20]:
        job_time = _coerce_dt(job.started_at) or _coerce_dt(job.finished_at)
        request_items.append(
            {
                "time": job_time.isoformat() if job_time else None,
                "source_agent": "operator" if job.trigger_type == "manual" else "B",
                "request": "Targeted context refresh" if job.trigger_type == "manual" else "Announcement context refresh",
                "status": _map_job_status(job.status),
                "inferred": True,
                "evidence": f"context_job:{job.job_id}",
            }
        )

    request_items = sorted(
        request_items,
        key=lambda x: _coerce_dt(x.get("time")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:20]

    auto_jobs = [job for job in recent_jobs if job.trigger_type == "auto_if_needed"]
    failed_jobs = [job for job in recent_jobs if job.status in {"fail", "partial"}]
    successful_jobs = [job for job in recent_jobs if job.status == "success"]
    base_progress = int((len(successful_jobs) / max(1, len(recent_jobs))) * 100) if recent_jobs else 0
    if narrator_running and open_recent_jobs:
        base_scraper_status = "running"
    elif recent_jobs and len(failed_jobs) > len(successful_jobs):
        base_scraper_status = "degraded"
    else:
        base_scraper_status = "idle"

    packs_stmt = select(EvidencePack).order_by(desc(EvidencePack.created_at)).limit(40)
    packs_rows = (await session.execute(packs_stmt)).scalars().all()
    recent_packs = [
        row for row in packs_rows
        if _coerce_dt(row.created_at) and _coerce_dt(row.created_at) >= now_utc - timedelta(minutes=safe_window)
    ]
    avg_coverage = 0.0
    if recent_packs:
        avg_coverage = sum(float(row.coverage_score or 0.0) for row in recent_packs) / len(recent_packs)
    corroboration_progress = int(max(0.0, min(100.0, avg_coverage * 100.0)))

    scrapers = {
        "items": [
            {
                "name": "Announcement Context Refresher",
                "status": base_scraper_status,
                "progress_pct": base_progress,
                "last_update_at": (
                    (_coerce_dt(recent_jobs[0].finished_at) or _coerce_dt(recent_jobs[0].started_at)).isoformat()
                    if recent_jobs else None
                ),
                "inferred": True,
            },
            {
                "name": "Canonical Source Refetch",
                "status": "running" if narrator_running and any(job.finished_at is None for job in auto_jobs[:5]) else "degraded" if auto_jobs and len([j for j in auto_jobs if j.status in {'fail', 'partial'}]) > 0 else "idle",
                "progress_pct": int((len([j for j in auto_jobs if j.status == "success"]) / max(1, len(auto_jobs))) * 100) if auto_jobs else 0,
                "last_update_at": (
                    (_coerce_dt(auto_jobs[0].finished_at) or _coerce_dt(auto_jobs[0].started_at)).isoformat()
                    if auto_jobs else None
                ),
                "inferred": True,
            },
            {
                "name": "Corroboration Fetch",
                "status": "running" if narrator_running and recent_packs and _coerce_dt(recent_packs[0].created_at) and _coerce_dt(recent_packs[0].created_at) >= now_utc - timedelta(minutes=2) else "degraded" if recent_packs and avg_coverage < 0.6 else "idle",
                "progress_pct": corroboration_progress,
                "last_update_at": _coerce_dt(recent_packs[0].created_at).isoformat() if recent_packs and _coerce_dt(recent_packs[0].created_at) else None,
                "inferred": True,
            },
        ]
    }

    events: list[dict[str, Any]] = []
    for run in narrator_runs[:10]:
        run_status = str(run.get("status") or "").lower()
        event_time = _coerce_dt(run.get("finished_at")) or _coerce_dt(run.get("started_at"))
        if not event_time:
            continue
        if run_status == "running":
            message = "Agent F started narrative synthesis"
        elif run_status == "success":
            message = "Agent F completed narrative cycle"
        elif run_status == "partial":
            message = "Agent F completed cycle with degraded outputs"
        else:
            message = "Agent F cycle failed"
        events.append(
            {
                "time": event_time.isoformat(),
                "level": _event_level_from_status(run_status),
                "message": message,
                "source": "agent_f",
            }
        )

    upstream_source_map = {"A": "agent_a", "B": "agent_b", "C": "agent_c", "D": "agent_d", "E": "agent_e"}
    for key, run in upstream_latest.items():
        if not run:
            continue
        run_status = str(run.get("status") or "").lower()
        event_time = _coerce_dt(run.get("finished_at")) or _coerce_dt(run.get("started_at"))
        if not event_time:
            continue
        if event_time < now_utc - timedelta(minutes=safe_window):
            continue
        if run_status not in {"success", "partial", "fail"}:
            continue
        events.append(
            {
                "time": event_time.isoformat(),
                "level": _event_level_from_status(run_status),
                "message": f"{upstream_source_map[key].replace('_', ' ').title()} returned {run_status} data",
                "source": upstream_source_map[key],
            }
        )

    for job in recent_jobs[:20]:
        event_time = _coerce_dt(job.finished_at) or _coerce_dt(job.started_at)
        if not event_time:
            continue
        events.append(
            {
                "time": event_time.isoformat(),
                "level": "error" if job.status == "fail" else "warn" if job.status == "partial" else "info",
                "message": f"Context refresh ({job.trigger_type}) {job.status}",
                "source": "agent_f",
            }
        )

    events = sorted(
        events,
        key=lambda x: _coerce_dt(x.get("time")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:safe_events]

    cycles: list[dict[str, Any]] = []
    for run in narrator_runs[:safe_cycles]:
        started = _coerce_dt(run.get("started_at"))
        duration = _duration_seconds(run, now_utc)
        run_id = str(run.get("run_id") or "")
        cycles.append(
            {
                "cycle_id": f"#{run_id.replace('-', '')[-4:].upper()}" if run_id else "#----",
                "run_id": run_id or None,
                "start": started.isoformat() if started else None,
                "duration_seconds": int(duration) if duration is not None else None,
                "result": str(run.get("status") or "").lower() or "pending_data",
                "status_reason": run.get("status_reason"),
            }
        )

    latest_success = next(
        (
            _coerce_dt(run.get("finished_at")) or _coerce_dt(run.get("started_at"))
            for run in narrator_runs
            if str(run.get("status") or "").lower() in {"success", "partial"}
        ),
        None,
    )
    freshness_minutes = _minutes_since(latest_success, now_utc)
    if freshness_minutes is None:
        freshness_status = "degraded"
    elif freshness_minutes <= 30:
        freshness_status = "ok"
    elif freshness_minutes <= 120:
        freshness_status = "stale"
    else:
        freshness_status = "degraded"

    healthy_agents, total_agents = connectivity
    connectivity_status = "ok" if healthy_agents == total_agents else "degraded"

    latency_samples = [
        _duration_seconds(run, now_utc)
        for run in narrator_runs
        if str(run.get("status") or "").lower() in {"success", "partial", "fail"} and _duration_seconds(run, now_utc) is not None
    ]
    latency_values = [float(v) for v in latency_samples if v is not None]
    p50 = float(median(latency_values)) if latency_values else 0.0
    p95 = _percentile(latency_values, 0.95) if latency_values else 0.0
    latency_status = "ok" if p95 <= 30 else "degraded"

    scraper_active = len(open_recent_jobs)
    scraper_recent_failures = len([job for job in recent_jobs if job.status in {"fail", "partial"}])
    scraper_status = "ok" if scraper_recent_failures == 0 else "degraded"

    health = {
        "data_freshness": {
            "status": freshness_status,
            "minutes_since_last_success": int(freshness_minutes) if freshness_minutes is not None else None,
        },
        "agent_connectivity": {
            "status": connectivity_status,
            "healthy_agents": healthy_agents,
            "total_agents": total_agents,
        },
        "pipeline_latency": {
            "status": latency_status,
            "p50_seconds": round(p50, 2),
            "p95_seconds": round(p95, 2),
        },
        "scraper_health": {
            "status": scraper_status,
            "active_jobs": scraper_active,
            "recent_failures": scraper_recent_failures,
        },
    }

    status_payload = {
        "agent_status": agent_status,
        "current_task": current_task,
        "progress_pct": progress_pct,
        "progress_label": "Narrative Generation Progress",
        "started_at": started_at.isoformat() if started_at else None,
        "estimated_completion_at": eta.isoformat() if eta else None,
        "last_cycle_id": latest_narrator.get("run_id") if latest_narrator else None,
        "status_reason": status_reason,
    }

    snapshot = {
        "generated_at": now_utc.isoformat(),
        "status": status_payload,
        "pipeline": {
            "window_minutes": safe_window,
            "nodes": nodes,
            "links": links,
        },
        "requests": {
            "items": request_items[:20],
            "limit": 20,
        },
        "scrapers": scrapers,
        "events": {
            "items": events,
            "limit": safe_events,
        },
        "cycles": {
            "items": cycles,
            "limit": safe_cycles,
        },
        "health": health,
    }
    return snapshot


async def get_monitor_status(session: AsyncSession, *, window_minutes: int = 30) -> dict[str, Any]:
    snapshot = await build_monitor_snapshot(session, window_minutes=window_minutes, events_limit=20, cycles_limit=5)
    return snapshot["status"]


async def get_monitor_pipeline(session: AsyncSession, *, window_minutes: int = 30) -> dict[str, Any]:
    snapshot = await build_monitor_snapshot(session, window_minutes=window_minutes, events_limit=20, cycles_limit=5)
    return snapshot["pipeline"]


async def get_monitor_requests(session: AsyncSession, *, limit: int = 20, window_minutes: int = 30) -> dict[str, Any]:
    snapshot = await build_monitor_snapshot(session, window_minutes=window_minutes, events_limit=20, cycles_limit=5)
    items = snapshot["requests"]["items"][: max(1, min(limit, 100))]
    return {"items": items, "limit": max(1, min(limit, 100))}


async def get_monitor_scrapers(session: AsyncSession, *, window_minutes: int = 30) -> dict[str, Any]:
    snapshot = await build_monitor_snapshot(session, window_minutes=window_minutes, events_limit=20, cycles_limit=5)
    return snapshot["scrapers"]


async def get_monitor_events(session: AsyncSession, *, limit: int = 20, window_minutes: int = 30) -> dict[str, Any]:
    snapshot = await build_monitor_snapshot(session, window_minutes=window_minutes, events_limit=max(limit, 20), cycles_limit=5)
    items = snapshot["events"]["items"][: max(1, min(limit, 100))]
    return {"items": items, "limit": max(1, min(limit, 100))}


async def get_monitor_cycles(session: AsyncSession, *, limit: int = 5, window_minutes: int = 30) -> dict[str, Any]:
    snapshot = await build_monitor_snapshot(session, window_minutes=window_minutes, events_limit=20, cycles_limit=max(limit, 5))
    items = snapshot["cycles"]["items"][: max(1, min(limit, 20))]
    return {"items": items, "limit": max(1, min(limit, 20))}


async def get_monitor_health(session: AsyncSession, *, window_minutes: int = 30) -> dict[str, Any]:
    snapshot = await build_monitor_snapshot(session, window_minutes=window_minutes, events_limit=20, cycles_limit=5)
    return snapshot["health"]
