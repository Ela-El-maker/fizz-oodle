from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from apps.core.config import get_settings
from apps.core.events import publish_run_command
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


WINDOW_STEPS = {
    "daily": [
        {"agent": "briefing"},
        {"agent": "announcements"},
        {"agent": "analyst", "report_type": "daily"},
    ],
    "weekly": [
        {"agent": "sentiment"},
        {"agent": "archivist", "run_type": "weekly"},
        {"agent": "analyst", "report_type": "weekly"},
    ],
}


def _period_key_for_window(window: str) -> date:
    today_eat = datetime.now(ZoneInfo("Africa/Nairobi")).date()
    if window == "weekly":
        return today_eat - timedelta(days=today_eat.weekday())
    return today_eat


async def _run_ledger_internal_post(path: str, params: dict | None = None, json_body: dict | None = None) -> dict:
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"http://run-ledger-service:8011{path}",
            params=clean,
            json=json_body,
            headers={"X-Internal-Api-Key": settings.INTERNAL_API_KEY},
        )
    resp.raise_for_status()
    return resp.json()


def _extract_email_outcome(agent_name: str, metrics: dict) -> tuple[bool, str | None]:
    if agent_name == "sentiment":
        return bool(metrics.get("digest_sent")), metrics.get("digest_error")
    return bool(metrics.get("email_sent")), metrics.get("email_error")


async def _wait_for_terminal_run(run_id: str, agent_name: str) -> dict:
    timeout = max(10, int(settings.EMAIL_VALIDATION_WAIT_TIMEOUT_SECONDS))
    poll = max(1, int(settings.EMAIL_VALIDATION_POLL_INTERVAL_SECONDS))
    elapsed = 0
    while elapsed <= timeout:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "http://run-ledger-service:8011/runs",
                params={"agent_name": agent_name, "limit": 200},
                headers={"X-API-Key": settings.API_KEY},
            )
        resp.raise_for_status()
        payload = resp.json()
        item = next((row for row in payload.get("items", []) if row.get("run_id") == run_id), None)
        if item and item.get("status") in {"success", "partial", "fail"}:
            return item
        await asyncio.sleep(poll)
        elapsed += poll
    return {
        "run_id": run_id,
        "agent_name": agent_name,
        "status": "fail",
        "metrics": {},
        "error_message": "validation_timeout",
    }


async def run_email_validation(window: str, *, force: bool = False, recipients_override: str | None = None) -> dict:
    normalized_window = (window or "daily").strip().lower()
    if normalized_window not in WINDOW_STEPS:
        raise ValueError(f"Unsupported validation window: {window}")
    if not settings.EMAIL_VALIDATION_ENABLED:
        return {"accepted": False, "reason": "email_validation_disabled", "window": normalized_window}

    recipients = (recipients_override or settings.EMAIL_VALIDATION_RECIPIENTS or settings.EMAIL_RECIPIENTS).strip()
    if not recipients:
        return {"accepted": False, "reason": "no_validation_recipients", "window": normalized_window}

    period_key = _period_key_for_window(normalized_window)
    start_payload = await _run_ledger_internal_post(
        "/internal/email-validation/start",
        params={
            "window": normalized_window,
            "period_key": period_key.isoformat(),
            "force": force,
        },
    )
    validation_run_id = start_payload["validation_run_id"]
    if start_payload.get("reused") and not force:
        return {
            "accepted": True,
            "validation_run_id": validation_run_id,
            "window": normalized_window,
            "period_key": period_key.isoformat(),
            "reused": True,
            "status": start_payload.get("status"),
            "summary": start_payload.get("summary_json") or {},
        }

    step_results: list[dict] = []
    for step in WINDOW_STEPS[normalized_window]:
        agent_name = step["agent"]
        run_id = str(uuid4())
        command = await publish_run_command(
            agent_name=agent_name,
            run_id=run_id,
            report_type=step.get("report_type"),
            run_type=step.get("run_type"),
            period_key=period_key.isoformat(),
            force_send=True,
            email_recipients_override=recipients,
        )
        terminal = await _wait_for_terminal_run(run_id=run_id, agent_name=agent_name)
        metrics = terminal.get("metrics") or {}
        email_sent, email_error = _extract_email_outcome(agent_name, metrics)
        step_status = (
            "success"
            if terminal.get("status") in {"success", "partial"} and email_sent and not email_error
            else "fail"
        )
        step_row = {
            "agent_name": agent_name,
            "run_id": run_id,
            "command_id": command.get("command_id"),
            "status": step_status,
            "run_status": terminal.get("status"),
            "email_sent": email_sent,
            "email_error": email_error,
            "metrics": metrics,
            "error_message": terminal.get("error_message"),
        }
        step_results.append(step_row)
        await _run_ledger_internal_post(
            f"/internal/email-validation/{validation_run_id}/step",
            json_body={
                "agent_name": agent_name,
                "run_id": run_id,
                "status": step_status,
                "email_sent": email_sent,
                "email_error": email_error,
                "metrics_json": metrics,
            },
        )

    overall_status = "success" if all(s["status"] == "success" for s in step_results) else "fail"
    summary = {
        "window": normalized_window,
        "period_key": period_key.isoformat(),
        "recipients": recipients,
        "steps": step_results,
        "all_passed": overall_status == "success",
    }
    await _run_ledger_internal_post(
        f"/internal/email-validation/{validation_run_id}/finish",
        json_body={"status": overall_status, "summary_json": summary},
    )
    return {
        "accepted": True,
        "validation_run_id": validation_run_id,
        "window": normalized_window,
        "period_key": period_key.isoformat(),
        "status": overall_status,
        "summary": summary,
    }
