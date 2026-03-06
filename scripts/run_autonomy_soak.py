#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

TERMINAL_STATUSES = {"success", "partial", "fail", "stale_timeout"}
GOOD_TERMINAL_STATUSES = {"success", "partial"}
STALE_TTLS_SECONDS = {
    "briefing": 25 * 60,
    "announcements": 25 * 60,
    "sentiment": 45 * 60,
    "analyst": 30 * 60,
    "archivist": 30 * 60,
}


@dataclass
class SoakConfig:
    base_url: str
    api_key: str
    duration_hours: float
    interval_seconds: int
    out_dir: Path
    timeout_seconds: int


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _http_get(config: SoakConfig, path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{config.base_url.rstrip('/')}{path}"
    response = requests.get(
        url,
        headers={"X-API-Key": config.api_key},
        params=params,
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def _collect_snapshot(config: SoakConfig) -> dict[str, Any]:
    collected_at = _now_utc().isoformat()
    snapshot: dict[str, Any] = {"collected_at": collected_at}
    endpoints = [
        ("health", "/health", None),
        ("runs", "/runs", {"limit": 300}),
        ("announcement_sources", "/sources/health", None),
        ("sentiment_sources", "/sentiment/sources/health", None),
        ("report_daily_latest", "/reports/latest", {"type": "daily"}),
        ("archive_weekly_latest", "/archive/latest", {"run_type": "weekly"}),
    ]
    for key, path, params in endpoints:
        try:
            snapshot[key] = _http_get(config, path, params)
        except Exception as exc:  # noqa: PERF203
            snapshot[key] = {"_error": str(exc)}
    return snapshot


def _latest_by_agent(runs: list[dict[str, Any]], agent: str) -> dict[str, Any] | None:
    candidates = [r for r in runs if str(r.get("agent_name", "")).lower() == agent]
    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            _parse_dt(r.get("finished_at")) or _parse_dt(r.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    return candidates[0]


def _aggregate(config: SoakConfig, snapshots: list[dict[str, Any]], window_start: datetime, window_end: datetime) -> dict[str, Any]:
    all_runs_by_id: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        runs_payload = snap.get("runs")
        if not isinstance(runs_payload, dict):
            continue
        for run in runs_payload.get("items", []) or []:
            if not isinstance(run, dict):
                continue
            run_id = run.get("run_id")
            if isinstance(run_id, str) and run_id:
                all_runs_by_id[run_id] = run

    runs = list(all_runs_by_id.values())
    window_runs: list[dict[str, Any]] = []
    for run in runs:
        started = _parse_dt(run.get("started_at"))
        if started is None or started >= window_start:
            window_runs.append(run)

    terminal_count = sum(1 for r in window_runs if str(r.get("status", "")).lower() in TERMINAL_STATUSES)
    terminality_pct = round((terminal_count / len(window_runs) * 100.0), 2) if window_runs else 100.0

    per_agent: dict[str, Any] = {}
    for agent in ["briefing", "announcements", "sentiment", "analyst", "archivist"]:
        agent_runs = [r for r in window_runs if str(r.get("agent_name", "")).lower() == agent]
        statuses: dict[str, int] = {}
        for row in agent_runs:
            status = str(row.get("status", "pending_data")).lower()
            statuses[status] = statuses.get(status, 0) + 1
        total = len(agent_runs)
        terminal = sum(v for s, v in statuses.items() if s in TERMINAL_STATUSES)
        per_agent[agent] = {
            "total_runs": total,
            "terminal_runs": terminal,
            "terminality_pct": round((terminal / total * 100.0), 2) if total else 100.0,
            "status_counts": statuses,
        }

    stale_running: list[dict[str, Any]] = []
    now = window_end
    for row in window_runs:
        status = str(row.get("status", "")).lower()
        if status != "running":
            continue
        agent = str(row.get("agent_name", "")).lower()
        started = _parse_dt(row.get("started_at"))
        ttl = STALE_TTLS_SECONDS.get(agent)
        if started and ttl and (now - started).total_seconds() > ttl:
            stale_running.append(
                {
                    "run_id": row.get("run_id"),
                    "agent_name": agent,
                    "started_at": row.get("started_at"),
                    "status_reason": row.get("status_reason"),
                }
            )

    stale_reconciled_count = sum(1 for r in window_runs if bool(r.get("is_stale_reconciled")))
    stale_timeout_count = sum(
        1
        for r in window_runs
        if str(r.get("status", "")).lower() == "stale_timeout"
        or str(r.get("status_reason", "")).lower() == "stale_run_timeout"
    )

    latest_snapshot = snapshots[-1] if snapshots else {}
    ann_items = (latest_snapshot.get("announcement_sources") or {}).get("items") or []
    sent_items = (latest_snapshot.get("sentiment_sources") or {}).get("items") or []

    def _core_rates(items: list[Any]) -> dict[str, Any]:
        entries = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("required_for_success")):
                continue
            rate = item.get("success_rate_24h")
            entries.append(
                {
                    "source_id": item.get("source_id"),
                    "tier": item.get("tier"),
                    "success_rate_24h": rate,
                    "blocked_count_24h": item.get("blocked_count_24h"),
                    "last_error_type": item.get("last_error_type"),
                }
            )
        numeric = [float(e["success_rate_24h"]) for e in entries if isinstance(e.get("success_rate_24h"), (int, float))]
        return {
            "core_sources": entries,
            "core_success_rate_avg_24h_pct": round((sum(numeric) / len(numeric) * 100.0), 2) if numeric else None,
        }

    core_rates = {
        "announcements": _core_rates(ann_items),
        "sentiment": _core_rates(sent_items),
    }

    analyst_runs = [r for r in window_runs if str(r.get("agent_name", "")).lower() == "analyst"]
    analyst_terminal = [r for r in analyst_runs if str(r.get("status", "")).lower() in TERMINAL_STATUSES]
    feedback_applied = 0
    for row in analyst_terminal:
        metrics = row.get("metrics") or {}
        if isinstance(metrics, dict) and metrics.get("feedback_applied") is True:
            feedback_applied += 1
    d_feedback_applied_rate = round((feedback_applied / len(analyst_terminal) * 100.0), 2) if analyst_terminal else None

    latest_b = _latest_by_agent(window_runs, "announcements")
    latest_c = _latest_by_agent(window_runs, "sentiment")
    latest_d = _latest_by_agent(window_runs, "analyst")
    latest_e = _latest_by_agent(window_runs, "archivist")

    latest_d_metrics = (latest_d or {}).get("metrics") or {}
    latest_e_metrics = (latest_e or {}).get("metrics") or {}
    archive_latest = latest_snapshot.get("archive_weekly_latest") or {}
    archive_item = archive_latest.get("item") if isinstance(archive_latest, dict) else {}
    archive_summary = archive_item.get("summary") if isinstance(archive_item, dict) else {}
    latest_archive_metrics = archive_summary.get("metrics") if isinstance(archive_summary, dict) else {}
    if not isinstance(latest_archive_metrics, dict):
        latest_archive_metrics = {}

    e_input_mode = None
    if isinstance(latest_e_metrics, dict) and isinstance(latest_e_metrics.get("input_mode"), str):
        e_input_mode = latest_e_metrics["input_mode"]
    elif isinstance(latest_archive_metrics.get("input_mode"), str):
        e_input_mode = latest_archive_metrics["input_mode"]

    e_reports_considered = 0
    if isinstance(latest_e_metrics, dict) and isinstance(latest_e_metrics.get("reports_considered"), (int, float)):
        e_reports_considered = int(latest_e_metrics["reports_considered"])
    elif isinstance(latest_archive_metrics.get("reports_considered"), (int, float)):
        e_reports_considered = int(latest_archive_metrics["reports_considered"])

    b_ok = str((latest_b or {}).get("status", "")).lower() in GOOD_TERMINAL_STATUSES
    c_ok = str((latest_c or {}).get("status", "")).lower() in GOOD_TERMINAL_STATUSES
    d_ok = (
        str((latest_d or {}).get("status", "")).lower() in GOOD_TERMINAL_STATUSES
        and isinstance(latest_d_metrics, dict)
        and latest_d_metrics.get("input_chain") == "A+B+C"
    )
    e_ok = str((latest_e or {}).get("status", "")).lower() in GOOD_TERMINAL_STATUSES and (
        e_input_mode in {"analyst_only", "hybrid"} and e_reports_considered > 0
    )
    chain = {
        "b_latest_status": (latest_b or {}).get("status"),
        "c_latest_status": (latest_c or {}).get("status"),
        "d_latest_status": (latest_d or {}).get("status"),
        "e_latest_status": (latest_e or {}).get("status"),
        "d_input_chain": latest_d_metrics.get("input_chain") if isinstance(latest_d_metrics, dict) else None,
        "e_input_mode": e_input_mode,
        "e_reports_considered": e_reports_considered,
        "bc_ready": b_ok and c_ok,
        "d_ready_from_abc": d_ok,
        "e_ready_from_d": e_ok,
        "overall_chain_ok": b_ok and c_ok and d_ok and e_ok,
    }

    return {
        "window": {
            "start_utc": window_start.isoformat(),
            "end_utc": window_end.isoformat(),
            "duration_hours": config.duration_hours,
            "sample_interval_seconds": config.interval_seconds,
            "samples_collected": len(snapshots),
        },
        "runs_summary": {
            "total_runs_seen": len(window_runs),
            "terminal_runs_seen": terminal_count,
            "terminality_pct": terminality_pct,
            "per_agent": per_agent,
        },
        "core_source_success_rates": core_rates,
        "stale_reconciler": {
            "stale_running_count": len(stale_running),
            "stale_running_runs": stale_running,
            "stale_reconciled_count": stale_reconciled_count,
            "stale_timeout_count": stale_timeout_count,
        },
        "d_feedback_applied_rate": {
            "analyst_terminal_runs": len(analyst_terminal),
            "feedback_applied_runs": feedback_applied,
            "feedback_applied_rate_pct": d_feedback_applied_rate,
        },
        "chain_health": chain,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_markdown_summary(path: Path, aggregate: dict[str, Any]) -> None:
    window = aggregate["window"]
    runs = aggregate["runs_summary"]
    stale = aggregate["stale_reconciler"]
    chain = aggregate["chain_health"]
    feedback = aggregate["d_feedback_applied_rate"]
    lines = [
        "# AUTONOMY Sprint Soak Closure",
        "",
        f"- Start (UTC): `{window['start_utc']}`",
        f"- End (UTC): `{window['end_utc']}`",
        f"- Duration (hours): `{window['duration_hours']}`",
        f"- Samples collected: `{window['samples_collected']}`",
        "",
        "## Reliability",
        f"- Terminality: `{runs['terminality_pct']}%` ({runs['terminal_runs_seen']}/{runs['total_runs_seen']})",
        f"- Stale running count: `{stale['stale_running_count']}`",
        f"- Stale reconciled count: `{stale['stale_reconciled_count']}`",
        "",
        "## Chain",
        f"- BC ready: `{chain['bc_ready']}`",
        f"- D ready from ABC: `{chain['d_ready_from_abc']}`",
        f"- E ready from D: `{chain['e_ready_from_d']}`",
        f"- Overall chain OK: `{chain['overall_chain_ok']}`",
        "",
        "## Feedback Loop",
        f"- D feedback applied rate: `{feedback['feedback_applied_rate_pct']}`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config: SoakConfig) -> int:
    config.out_dir.mkdir(parents=True, exist_ok=True)
    samples_path = config.out_dir / "samples.jsonl"
    start = _now_utc()
    end = start + timedelta(hours=config.duration_hours)
    snapshots: list[dict[str, Any]] = []

    with samples_path.open("w", encoding="utf-8") as fh:
        while True:
            snap = _collect_snapshot(config)
            snapshots.append(snap)
            fh.write(json.dumps(snap) + "\n")
            fh.flush()

            now = _now_utc()
            if now >= end:
                break
            sleep_for = min(config.interval_seconds, max(1, int((end - now).total_seconds())))
            time.sleep(sleep_for)

    aggregate = _aggregate(config, snapshots, start, _now_utc())

    _write_json(config.out_dir / "runs_24h.json", aggregate["runs_summary"])
    _write_json(config.out_dir / "core_source_success_rates.json", aggregate["core_source_success_rates"])
    _write_json(config.out_dir / "stale_reconciler_results.json", aggregate["stale_reconciler"])
    _write_json(config.out_dir / "d_feedback_applied_rate.json", aggregate["d_feedback_applied_rate"])
    _write_json(config.out_dir / "chain_health_snapshot.json", aggregate["chain_health"])
    _write_json(config.out_dir / "soak_window.json", aggregate["window"])
    _write_markdown_summary(config.out_dir / "AUTONOMY_SPRINT_CLOSURE.md", aggregate)

    print(f"Wrote soak evidence to {config.out_dir}")
    return 0


def parse_args() -> SoakConfig:
    parser = argparse.ArgumentParser(description="Run 24h reliability soak evidence collector.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="change-me")
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out-dir", default="docs/evidence/autonomy_sprint/live")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    return SoakConfig(
        base_url=args.base_url,
        api_key=args.api_key,
        duration_hours=args.duration_hours,
        interval_seconds=max(5, int(args.interval_seconds)),
        out_dir=Path(args.out_dir),
        timeout_seconds=max(5, int(args.timeout_seconds)),
    )


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
