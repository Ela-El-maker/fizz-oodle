from __future__ import annotations

import asyncio
import hmac
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
import httpx
from pydantic import BaseModel

from apps.api.routers.auth import get_session_role, get_session_user, require_api_key, require_role
from apps.core.config import get_settings
from apps.core.events import publish_run_command
from apps.core.logger import configure_logging
from apps.core.session_auth import create_session_token, verify_session_token
from services.common.security import require_internal_api_key
from services.gateway.email_validation import run_email_validation
from services.common.metrics import setup_metrics

configure_logging()
settings = get_settings()
PROXY_TIMEOUT_SECONDS = max(10.0, float(getattr(settings, "GATEWAY_PROXY_TIMEOUT_SECONDS", 90)))

app = FastAPI(title="Gateway Service")
setup_metrics(app, "gateway")


AGENT_INTERNAL = {
    "briefing": settings.AGENT_A_SERVICE_URL,
    "announcements": settings.AGENT_B_SERVICE_URL,
    "sentiment": settings.AGENT_C_SERVICE_URL,
    "analyst": settings.AGENT_D_SERVICE_URL,
    "archivist": settings.AGENT_E_SERVICE_URL,
    "narrator": settings.AGENT_F_SERVICE_URL,
}

TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates"


def _load_html_template(name: str) -> str:
    path = TEMPLATE_ROOT / name
    if not path.exists():
        raise RuntimeError(f"Missing template: {path}")
    return path.read_text(encoding="utf-8")


class LoginRequest(BaseModel):
    username: str
    password: str


async def _forward_get(base: str, path: str, *, params: dict | None = None):
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            f"{base.rstrip('/')}{path}",
            params=clean_params,
            headers={"X-API-Key": settings.API_KEY},
        )
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="Upstream service error")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def _call_internal_post(base: str, path: str, *, params: dict | None = None):
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{base.rstrip('/')}{path}",
            params=clean_params,
            headers={"X-Internal-Api-Key": settings.INTERNAL_API_KEY},
        )
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="Upstream service error")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def _forward_post(base: str, path: str, *, params: dict | None = None):
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{base.rstrip('/')}{path}",
            params=clean_params,
            headers={"X-API-Key": settings.API_KEY},
        )
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="Upstream service error")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


def _is_ws_authenticated(websocket: WebSocket) -> bool:
    if not settings.API_KEY:
        return True
    supplied = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    if supplied and hmac.compare_digest(supplied, settings.API_KEY):
        return True
    if settings.SESSION_AUTH_ENABLED:
        token = websocket.cookies.get(settings.SESSION_COOKIE_NAME)
        if token:
            payload = verify_session_token(token, secret=settings.SESSION_SECRET)
            if payload and isinstance(payload.get("sub"), str) and payload.get("sub"):
                return True
    return False


async def _fetch_monitor_snapshot(*, window_minutes: int = 30, events_limit: int = 20, cycles_limit: int = 5) -> dict:
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/snapshot",
        params={
            "window_minutes": window_minutes,
            "events_limit": events_limit,
            "cycles_limit": cycles_limit,
        },
    )


async def _fetch_scheduler_snapshot(*, hours: int = 24, events_limit: int = 50, failed_agent: str | None = None) -> dict:
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/scheduler/monitor/snapshot",
        params={
            "hours": hours,
            "events_limit": events_limit,
            "failed_agent": failed_agent,
        },
    )


@app.get("/health")
async def health():
    checks: dict = {}
    overall = "ok"
    async with httpx.AsyncClient(timeout=5.0) as client:
        targets = {
            "agent_a": settings.AGENT_A_SERVICE_URL,
            "agent_b": settings.AGENT_B_SERVICE_URL,
            "agent_c": settings.AGENT_C_SERVICE_URL,
            "agent_d": settings.AGENT_D_SERVICE_URL,
            "agent_e": settings.AGENT_E_SERVICE_URL,
            "agent_f": settings.AGENT_F_SERVICE_URL,
            "run_ledger": "http://run-ledger-service:8011",
            "scheduler": "http://scheduler-service:8010",
        }
        import time as _time
        for name, base in targets.items():
            t0 = _time.monotonic()
            try:
                resp = await client.get(
                    f"{base}/internal/health",
                    headers={"X-Internal-Api-Key": settings.INTERNAL_API_KEY},
                )
                latency_ms = round((_time.monotonic() - t0) * 1000, 1)
                if 200 <= resp.status_code < 300:
                    checks[name] = {**resp.json(), "latency_ms": latency_ms}
                else:
                    checks[name] = {"status": "fail", "error": f"http_{resp.status_code}", "latency_ms": latency_ms}
                    overall = "degraded"
            except Exception:
                latency_ms = round((_time.monotonic() - t0) * 1000, 1)
                checks[name] = {"status": "fail", "error": "service_unavailable", "latency_ms": latency_ms}
                overall = "degraded"

        # Fetch latest run status per agent from the run ledger
        agent_runs: dict = {}
        for agent_key in ("briefing", "announcements", "sentiment", "analyst", "archivist", "narrator"):
            try:
                resp = await client.get(
                    f"http://run-ledger-service:8011/runs/latest/{agent_key}",
                    headers={"X-API-Key": settings.API_KEY},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    agent_runs[agent_key] = {
                        "status": data.get("status"),
                        "started_at": data.get("started_at"),
                        "finished_at": data.get("finished_at"),
                        "is_stale": data.get("is_stale_reconciled", False),
                    }
            except Exception:
                pass

    # Source health snapshot (non-blocking best-effort)
    source_health_snapshot: dict | None = None
    try:
        from apps.scrape_core.source_health import get_source_health_tracker
        tracker = get_source_health_tracker()
        source_health_snapshot = tracker.snapshot()
    except Exception:
        pass

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": checks,
        "latest_runs": agent_runs,
        "source_health": source_health_snapshot,
    }


@app.post("/auth/login")
async def auth_login(payload: LoginRequest, response: Response):
    username = payload.username.strip()
    if (
        username != settings.OPERATOR_USERNAME
        or not hmac.compare_digest(payload.password, settings.OPERATOR_PASSWORD)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    role = "admin" if username == settings.OPERATOR_USERNAME else "viewer"
    token = create_session_token(
        username=username,
        secret=settings.SESSION_SECRET,
        ttl_seconds=settings.SESSION_TTL_SECONDS,
        role=role,
    )
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )
    return {"ok": True, "user": {"username": username, "role": role}}


@app.post("/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/auth/me")
async def auth_me(request: Request):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role = get_session_role(request) or "viewer"
    return {"authenticated": True, "user": {"username": user, "role": role}}


@app.get("/runs")
async def runs(
    agent_name: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/runs",
        params={"agent_name": agent_name, "status": status_filter, "limit": limit},
    )


@app.post("/run/{agent}", status_code=status.HTTP_202_ACCEPTED)
async def run_agent(
    agent: str,
    report_type: str | None = None,
    run_type: str | None = None,
    period_key: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
    _auth: None = Depends(require_role("operator")),
):
    agent_name = agent.strip().lower()
    if agent_name not in AGENT_INTERNAL:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent}")

    run_id = str(uuid4())
    resolved_report_type = report_type
    resolved_run_type = run_type
    if agent_name == "archivist":
        # Backward compatibility: archivist historically used report_type in query.
        resolved_run_type = run_type or report_type
    if agent_name == "analyst" and resolved_report_type is None and run_type:
        # Backward compatibility for callers using run_type with analyst.
        resolved_report_type = run_type
    command = await publish_run_command(
        agent_name=agent_name,
        run_id=run_id,
        trigger_type="manual",
        requested_by="operator",
        report_type=resolved_report_type,
        run_type=resolved_run_type,
        period_key=period_key,
        force_send=force_send,
        email_recipients_override=email_recipients_override,
    )
    return {
        "run_id": run_id,
        "agent_name": agent_name,
        "status": "queued",
        "started_at": command["requested_at"],
        "finished_at": None,
        "metrics": {},
    }


@app.post("/internal/ops/email-validation/run", dependencies=[Depends(require_internal_api_key)])
async def internal_email_validation_run(
    window: str = "daily",
    force: bool = False,
):
    return await run_email_validation(
        window=window,
        force=force,
        recipients_override=settings.EMAIL_VALIDATION_RECIPIENTS,
    )


@app.post("/admin/email-validation/run")
async def admin_email_validation_run(
    window: str = "daily",
    force: bool = False,
    _auth: None = Depends(require_role("admin")),
):
    return await run_email_validation(
        window=window,
        force=force,
        recipients_override=settings.EMAIL_VALIDATION_RECIPIENTS,
    )


@app.get("/sentiment/weekly")
async def sentiment_weekly(
    week_start: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(settings.AGENT_C_SERVICE_URL, "/sentiment/weekly", params={"week_start": week_start, "limit": limit, "offset": offset})


@app.get("/sentiment/themes/weekly")
async def sentiment_themes_weekly(
    week_start: str | None = None,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_C_SERVICE_URL,
        "/sentiment/themes/weekly",
        params={"week_start": week_start},
    )


@app.get("/announcements")
async def announcements_list(
    ticker: str | None = None,
    type: str | None = None,  # noqa: A002
    source_id: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    alerted: bool | None = None,
    scope: str | None = None,
    theme: str | None = None,
    kenya_impact_min: int | None = None,
    global_only: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_B_SERVICE_URL,
        "/announcements",
        params={
            "ticker": ticker,
            "type": type,
            "source_id": source_id,
            "from": from_,
            "to": to,
            "alerted": alerted,
            "scope": scope,
            "theme": theme,
            "kenya_impact_min": kenya_impact_min,
            "global_only": global_only,
            "limit": limit,
            "offset": offset,
        },
    )


@app.get("/announcements/stats")
async def announcements_stats(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_B_SERVICE_URL, "/announcements/stats")


@app.get("/announcements/{announcement_id}")
async def announcements_get(announcement_id: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_B_SERVICE_URL, f"/announcements/{announcement_id}")


@app.get("/announcements/{announcement_id}/insight")
async def announcements_insight(
    announcement_id: str,
    refresh_context_if_needed: bool = True,
    force_regenerate: bool = False,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        f"/announcements/{announcement_id}/insight",
        params={
            "refresh_context_if_needed": refresh_context_if_needed,
            "force_regenerate": force_regenerate,
        },
    )


@app.post("/announcements/{announcement_id}/context/refresh")
async def announcements_context_refresh(
    announcement_id: str,
    _auth: None = Depends(require_api_key),
):
    return await _forward_post(
        settings.AGENT_F_SERVICE_URL,
        f"/announcements/{announcement_id}/context/refresh",
    )


@app.get("/stories/latest")
async def stories_latest(
    scope: str = "market",
    context: str = "prices",
    ticker: str | None = None,
    force_regenerate: bool = False,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/latest",
        params={
            "scope": scope,
            "context": context,
            "ticker": ticker,
            "force_regenerate": force_regenerate,
        },
    )


@app.get("/stories")
async def stories_list(
    scope: str | None = None,
    ticker: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories",
        params={
            "scope": scope,
            "ticker": ticker,
            "status": status_filter,
            "limit": limit,
            "offset": offset,
        },
    )


@app.get("/stories/{card_id}")
async def stories_get(card_id: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_F_SERVICE_URL, f"/stories/{card_id}")


@app.post("/stories/rebuild")
async def stories_rebuild(force_regenerate: bool = True, _auth: None = Depends(require_role("operator"))):
    return await _forward_post(
        settings.AGENT_F_SERVICE_URL,
        "/stories/rebuild",
        params={"force_regenerate": force_regenerate},
    )


@app.get("/stories/monitor/status")
async def stories_monitor_status(
    window_minutes: int = 30,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/status",
        params={"window_minutes": window_minutes},
    )


@app.get("/stories/monitor/pipeline")
async def stories_monitor_pipeline(
    window_minutes: int = 30,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/pipeline",
        params={"window_minutes": window_minutes},
    )


@app.get("/stories/monitor/requests")
async def stories_monitor_requests(
    limit: int = 20,
    window_minutes: int = 30,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/requests",
        params={"limit": limit, "window_minutes": window_minutes},
    )


@app.get("/stories/monitor/scrapers")
async def stories_monitor_scrapers(
    window_minutes: int = 30,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/scrapers",
        params={"window_minutes": window_minutes},
    )


@app.get("/stories/monitor/events")
async def stories_monitor_events(
    limit: int = 20,
    window_minutes: int = 30,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/events",
        params={"limit": limit, "window_minutes": window_minutes},
    )


@app.get("/stories/monitor/cycles")
async def stories_monitor_cycles(
    limit: int = 5,
    window_minutes: int = 30,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/cycles",
        params={"limit": limit, "window_minutes": window_minutes},
    )


@app.get("/stories/monitor/health")
async def stories_monitor_health(
    window_minutes: int = 30,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_F_SERVICE_URL,
        "/stories/monitor/health",
        params={"window_minutes": window_minutes},
    )


@app.get("/stories/monitor/snapshot")
async def stories_monitor_snapshot(
    window_minutes: int = 30,
    events_limit: int = 20,
    cycles_limit: int = 5,
    _auth: None = Depends(require_api_key),
):
    return await _fetch_monitor_snapshot(
        window_minutes=window_minutes,
        events_limit=events_limit,
        cycles_limit=cycles_limit,
    )


@app.websocket("/stories/monitor/ws")
async def stories_monitor_ws(websocket: WebSocket):
    if not _is_ws_authenticated(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last_heartbeat = datetime.now(timezone.utc)
    try:
        while True:
            try:
                snapshot = await _fetch_monitor_snapshot()
                await websocket.send_json(
                    {
                        "type": "snapshot",
                        "transport": "ws",
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "data": snapshot,
                    }
                )
            except Exception as exc:  # noqa: PERF203
                await websocket.send_json(
                    {
                        "type": "degraded",
                        "transport": "ws",
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "reason": str(exc),
                    }
                )

            now_utc = datetime.now(timezone.utc)
            if (now_utc - last_heartbeat).total_seconds() >= 15:
                await websocket.send_json({"type": "heartbeat", "generated_at": now_utc.isoformat()})
                last_heartbeat = now_utc
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


@app.get("/scheduler/monitor/status")
async def scheduler_monitor_status(_auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/scheduler/monitor/status")


@app.get("/scheduler/monitor/active")
async def scheduler_monitor_active(_auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/scheduler/monitor/active")


@app.get("/scheduler/monitor/upcoming")
async def scheduler_monitor_upcoming(hours: int = 24, _auth: None = Depends(require_api_key)):
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/scheduler/monitor/upcoming",
        params={"hours": hours},
    )


@app.get("/scheduler/monitor/history")
async def scheduler_monitor_history(limit: int = 50, _auth: None = Depends(require_api_key)):
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/scheduler/monitor/history",
        params={"limit": limit},
    )


@app.get("/scheduler/monitor/pipeline")
async def scheduler_monitor_pipeline(window_minutes: int = 120, _auth: None = Depends(require_api_key)):
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/scheduler/monitor/pipeline",
        params={"window_minutes": window_minutes},
    )


@app.get("/scheduler/monitor/email")
async def scheduler_monitor_email(_auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/scheduler/monitor/email")


@app.get("/scheduler/monitor/events")
async def scheduler_monitor_events(limit: int = 50, _auth: None = Depends(require_api_key)):
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/scheduler/monitor/events",
        params={"limit": limit},
    )


@app.get("/scheduler/monitor/heatmap")
async def scheduler_monitor_heatmap(hours: int = 24, _auth: None = Depends(require_api_key)):
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/scheduler/monitor/heatmap",
        params={"hours": hours},
    )


@app.get("/scheduler/monitor/impact")
async def scheduler_monitor_impact(failed_agent: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(
        "http://run-ledger-service:8011",
        "/scheduler/monitor/impact",
        params={"failed_agent": failed_agent},
    )


@app.get("/scheduler/monitor/snapshot")
async def scheduler_monitor_snapshot(
    hours: int = 24,
    events_limit: int = 50,
    failed_agent: str | None = None,
    _auth: None = Depends(require_api_key),
):
    return await _fetch_scheduler_snapshot(hours=hours, events_limit=events_limit, failed_agent=failed_agent)


@app.post("/scheduler/control/dispatch/{schedule_key}")
async def scheduler_control_dispatch(schedule_key: str, _auth: None = Depends(require_role("admin"))):
    return await _call_internal_post("http://scheduler-service:8010", f"/internal/dispatch/{schedule_key}")


@app.post("/scheduler/control/retry/{run_id}")
async def scheduler_control_retry(run_id: str, _auth: None = Depends(require_role("operator"))):
    return await _forward_post("http://run-ledger-service:8011", f"/scheduler/control/retry/{run_id}")


@app.post("/scheduler/control/rebuild-narrator")
async def scheduler_control_rebuild_narrator(force_regenerate: bool = True, _auth: None = Depends(require_role("admin"))):
    return await _forward_post(
        settings.AGENT_F_SERVICE_URL,
        "/stories/rebuild",
        params={"force_regenerate": force_regenerate},
    )


@app.websocket("/scheduler/monitor/ws")
async def scheduler_monitor_ws(websocket: WebSocket):
    if not _is_ws_authenticated(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last_heartbeat = datetime.now(timezone.utc)
    try:
        while True:
            try:
                snapshot = await _fetch_scheduler_snapshot()
                await websocket.send_json(
                    {
                        "type": "snapshot",
                        "transport": "ws",
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "data": snapshot,
                    }
                )
            except Exception as exc:  # noqa: PERF203
                await websocket.send_json(
                    {
                        "type": "degraded",
                        "transport": "ws",
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "reason": str(exc),
                    }
                )

            now_utc = datetime.now(timezone.utc)
            if (now_utc - last_heartbeat).total_seconds() >= 15:
                await websocket.send_json({"type": "heartbeat", "generated_at": now_utc.isoformat()})
                last_heartbeat = now_utc
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


@app.get("/sources/health")
async def sources_health(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_B_SERVICE_URL, "/sources/health")


@app.get("/briefings/latest")
async def briefings_latest(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/briefings/latest")


@app.get("/briefings/daily")
async def briefings_daily(date: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/briefings/daily", params={"date": date})


@app.get("/briefing/sources/health")
async def briefing_sources_health(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/briefing/sources/health")


@app.get("/internal/email/executive/latest")
async def executive_email_latest(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/internal/email/executive/latest")


@app.get("/prices/daily")
async def prices_daily(date: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/prices/daily", params={"date": date})


@app.get("/universe/summary")
async def universe_summary(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/universe/summary")


@app.get("/prices/{ticker}")
async def prices_ticker(
    ticker: str,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, f"/prices/{ticker}", params={"from": from_, "to": to})


@app.get("/fx/daily")
async def fx_daily(date: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/fx/daily", params={"date": date})


@app.get("/index/daily")
async def index_daily(date: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/index/daily", params={"date": date})


@app.get("/sentiment/weekly/{ticker}")
async def sentiment_weekly_ticker(
    ticker: str,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(settings.AGENT_C_SERVICE_URL, f"/sentiment/weekly/{ticker}", params={"from": from_, "to": to})


@app.get("/sentiment/raw")
async def sentiment_raw(
    ticker: str | None = None,
    source_id: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(
        settings.AGENT_C_SERVICE_URL,
        "/sentiment/raw",
        params={"ticker": ticker, "source_id": source_id, "from": from_, "to": to, "limit": limit, "offset": offset},
    )


@app.get("/sentiment/sources/health")
async def sentiment_source_health(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_C_SERVICE_URL, "/sentiment/sources/health")


@app.get("/sentiment/digest/latest")
async def sentiment_digest_latest(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_C_SERVICE_URL, "/sentiment/digest/latest")


@app.get("/sentiment/digest")
async def sentiment_digest(week_start: str | None = None, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_C_SERVICE_URL, "/sentiment/digest", params={"week_start": week_start})


@app.get("/v1/sentiment/latest")
async def sentiment_latest_compat(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_C_SERVICE_URL, "/v1/sentiment/latest")


@app.get("/v1/prices/latest")
async def prices_latest_compat(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_A_SERVICE_URL, "/prices/latest")


@app.get("/v1/announcements/recent")
async def announcements_recent_compat(limit: int = 50, _auth: None = Depends(require_api_key)):
    payload = await _forward_get(settings.AGENT_B_SERVICE_URL, "/announcements", params={"limit": limit, "offset": 0})
    return payload


@app.get("/reports/latest")
async def reports_latest(type: str = Query(default="daily"), _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_D_SERVICE_URL, "/reports/latest", params={"type": type})


@app.get("/reports")
async def reports_list(
    type: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(settings.AGENT_D_SERVICE_URL, "/reports", params={"type": type, "from": from_, "to": to, "limit": limit, "offset": offset})


@app.get("/reports/{report_id}")
async def report_get(report_id: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_D_SERVICE_URL, f"/reports/{report_id}")


@app.get("/reports/{report_id}/inputs")
async def report_inputs(report_id: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_D_SERVICE_URL, f"/reports/{report_id}/inputs")


@app.get("/admin/reports")
async def admin_reports(request: Request, _auth: None = Depends(require_role("admin"))):
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{settings.AGENT_D_SERVICE_URL}/admin/reports",
            params=dict(request.query_params),
            headers={"X-API-Key": settings.API_KEY},
        )
    return Response(content=resp.text, status_code=resp.status_code, media_type="text/html")


@app.post("/admin/reports/trigger")
async def admin_reports_trigger(
    report_type: str = "daily",
    period_key: str | None = None,
    _auth: None = Depends(require_role("admin")),
):
    run_id = str(uuid4())
    command = await publish_run_command(
        agent_name="analyst",
        run_id=run_id,
        trigger_type="manual",
        requested_by="operator",
        report_type=report_type,
        period_key=period_key,
        force_send=False,
    )
    return {"accepted": True, "run_id": run_id, "command_id": command["command_id"], "agent_name": "analyst"}


@app.post("/admin/reports/resend")
async def admin_reports_resend(
    report_type: str = "daily",
    period_key: str | None = None,
    force: bool = True,
    _auth: None = Depends(require_role("admin")),
):
    run_id = str(uuid4())
    command = await publish_run_command(
        agent_name="analyst",
        run_id=run_id,
        trigger_type="manual",
        requested_by="operator",
        report_type=report_type,
        period_key=period_key,
        force_send=force,
    )
    return {"accepted": True, "run_id": run_id, "command_id": command["command_id"], "agent_name": "analyst", "force_send": force}


@app.get("/patterns")
async def patterns_proxy(
    ticker: str | None = None,
    status: str | None = None,
    min_accuracy: float | None = None,
    limit: int = 100,
    _auth: None = Depends(require_api_key),
):
    return await _forward_get(settings.AGENT_E_SERVICE_URL, "/patterns", params={"ticker": ticker, "status": status, "min_accuracy": min_accuracy, "limit": limit})


@app.get("/patterns/active")
async def patterns_active_proxy(limit: int = 100, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_E_SERVICE_URL, "/patterns/active", params={"limit": limit})


@app.get("/patterns/summary")
async def patterns_summary_proxy(_auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_E_SERVICE_URL, "/patterns/summary")


@app.get("/patterns/ticker/{ticker}")
async def patterns_ticker_proxy(ticker: str, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_E_SERVICE_URL, f"/patterns/ticker/{ticker}")


@app.get("/impacts/{announcement_type}")
async def impacts_proxy(announcement_type: str, period_key: str | None = None, _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_E_SERVICE_URL, f"/impacts/{announcement_type}", params={"period_key": period_key})


@app.get("/archive/latest")
async def archive_latest_proxy(run_type: str = "weekly", _auth: None = Depends(require_api_key)):
    return await _forward_get(settings.AGENT_E_SERVICE_URL, "/archive/latest", params={"run_type": run_type})


@app.get("/insights/overview/latest")
async def insights_overview_latest(_auth: None = Depends(require_api_key)):
    def _compact_item(item: dict | None) -> dict | None:
        if not isinstance(item, dict):
            return None
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        return {
            "status": item.get("status"),
            "generated_at": item.get("generated_at") or item.get("created_at"),
            "period_key": item.get("period_key") or item.get("briefing_date") or item.get("week_start"),
            "subject": item.get("subject"),
            "degraded": item.get("degraded"),
            "human_summary": item.get("human_summary"),
            "human_summary_v2": item.get("human_summary_v2"),
            "quality": metrics.get("human_summary_v2", {}).get("quality")
            if isinstance(metrics.get("human_summary_v2"), dict)
            else None,
        }

    def _compact_announcements(stats: dict | None) -> dict:
        if not isinstance(stats, dict):
            return {"error": "unavailable"}
        return {
            "total": stats.get("total"),
            "alerted": stats.get("alerted"),
            "unalerted": stats.get("unalerted"),
            "by_type": stats.get("by_type"),
            "by_source": stats.get("by_source"),
            "human_summary": stats.get("human_summary"),
            "human_summary_v2": stats.get("human_summary_v2"),
        }

    def _compact_archive(payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return None
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return {
            "run_type": payload.get("run_type"),
            "period_key": payload.get("period_key"),
            "status": payload.get("status"),
            "created_at": payload.get("created_at"),
            "human_summary": payload.get("human_summary"),
            "human_summary_v2": payload.get("human_summary_v2"),
            "quality": summary.get("metrics", {}).get("human_summary_v2", {}).get("quality")
            if isinstance(summary.get("metrics"), dict)
            and isinstance(summary.get("metrics", {}).get("human_summary_v2"), dict)
            else None,
        }

    async with httpx.AsyncClient(timeout=30.0) as client:
        async def _safe_get(url: str, params: dict | None = None) -> dict:
            try:
                resp = await client.get(url, params=params, headers={"X-API-Key": settings.API_KEY})
                if resp.status_code >= 400:
                    return {"item": None, "error": f"http_{resp.status_code}"}
                return resp.json()
            except Exception as exc:  # noqa: PERF203
                return {"item": None, "error": str(exc)}

        briefing = await _safe_get(f"{settings.AGENT_A_SERVICE_URL}/briefings/latest")
        announcement_stats = await _safe_get(f"{settings.AGENT_B_SERVICE_URL}/announcements/stats")
        sentiment = await _safe_get(f"{settings.AGENT_C_SERVICE_URL}/sentiment/digest/latest")
        daily_report = await _safe_get(f"{settings.AGENT_D_SERVICE_URL}/reports/latest", params={"type": "daily"})
        weekly_report = await _safe_get(f"{settings.AGENT_D_SERVICE_URL}/reports/latest", params={"type": "weekly"})
        archive = await _safe_get(f"{settings.AGENT_E_SERVICE_URL}/archive/latest", params={"run_type": "weekly"})

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overview": {
            "briefing": _compact_item(briefing.get("item") if isinstance(briefing, dict) else None),
            "announcements": _compact_announcements(announcement_stats),
            "sentiment": _compact_item(sentiment.get("item") if isinstance(sentiment, dict) else None),
            "analyst_daily": _compact_item(daily_report.get("item") if isinstance(daily_report, dict) else None),
            "analyst_weekly": _compact_item(weekly_report.get("item") if isinstance(weekly_report, dict) else None),
            "archive_weekly": _compact_archive(archive.get("item") if isinstance(archive, dict) and "item" in archive else archive),
        },
    }


@app.get("/insights/ticker/{ticker}")
async def insights_ticker(ticker: str, _auth: None = Depends(require_api_key)):
    t = ticker.strip().upper()
    async with httpx.AsyncClient(timeout=30.0) as client:
        async def _safe_get(url: str, params: dict | None = None) -> dict:
            try:
                resp = await client.get(url, params=params, headers={"X-API-Key": settings.API_KEY})
                if resp.status_code >= 400:
                    return {"error": f"http_{resp.status_code}"}
                return resp.json()
            except Exception as exc:  # noqa: PERF203
                return {"error": str(exc)}

        prices = await _safe_get(f"{settings.AGENT_A_SERVICE_URL}/prices/{t}")
        anns = await _safe_get(f"{settings.AGENT_B_SERVICE_URL}/announcements", params={"ticker": t, "limit": 25, "offset": 0})
        sentiment = await _safe_get(f"{settings.AGENT_C_SERVICE_URL}/sentiment/weekly/{t}")
        patterns = await _safe_get(f"{settings.AGENT_E_SERVICE_URL}/patterns/ticker/{t}")

    return {
        "ticker": t,
        "price_context": prices,
        "announcement_context": anns,
        "sentiment_context": sentiment,
        "pattern_context": patterns,
    }


@app.get("/insights/quality/latest")
async def insights_quality_latest(_auth: None = Depends(require_api_key)):
    def _compact_analysis_item(payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return None
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        return {
            "status": payload.get("status"),
            "generated_at": payload.get("generated_at") or payload.get("created_at"),
            "period_key": payload.get("period_key"),
            "degraded": payload.get("degraded"),
            "human_summary_v2": payload.get("human_summary_v2"),
            "feedback_applied": metrics.get("feedback_applied"),
            "feedback_coverage_pct": metrics.get("feedback_coverage_pct"),
            "status_reason": metrics.get("status_reason"),
        }

    def _compact_archive_quality(payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return None
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
        return {
            "run_type": payload.get("run_type"),
            "period_key": payload.get("period_key"),
            "status": payload.get("status"),
            "created_at": payload.get("created_at"),
            "human_summary_v2": payload.get("human_summary_v2"),
            "upstream_quality_score": metrics.get("upstream_quality_score"),
            "degraded": metrics.get("degraded"),
            "warnings": metrics.get("warnings", []),
        }

    async with httpx.AsyncClient(timeout=30.0) as client:
        async def _safe_get(url: str) -> dict:
            try:
                resp = await client.get(url, headers={"X-API-Key": settings.API_KEY})
                if resp.status_code >= 400:
                    return {"items": [], "error": f"http_{resp.status_code}"}
                return resp.json()
            except Exception as exc:  # noqa: PERF203
                return {"items": [], "error": str(exc)}

        b_sources = await _safe_get(f"{settings.AGENT_B_SERVICE_URL}/sources/health")
        c_sources = await _safe_get(f"{settings.AGENT_C_SERVICE_URL}/sentiment/sources/health")
        a_sources = await _safe_get(f"{settings.AGENT_A_SERVICE_URL}/briefing/sources/health")
        d_latest = await _safe_get(f"{settings.AGENT_D_SERVICE_URL}/reports/latest?type=daily")
        e_latest = await _safe_get(f"{settings.AGENT_E_SERVICE_URL}/archive/latest?run_type=weekly")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_quality": {
            "briefing": a_sources.get("items", []),
            "announcements": b_sources.get("items", []),
            "sentiment": c_sources.get("items", []),
        },
        "analysis_quality": {
            "analyst_latest": _compact_analysis_item((d_latest.get("item") or {}) if isinstance(d_latest, dict) else {}),
            "archivist_latest": _compact_archive_quality((e_latest.get("item") or e_latest) if isinstance(e_latest, dict) else {}),
        },
    }


@app.get("/email-validation/latest")
async def email_validation_latest(window: str | None = None, _auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/email-validation/latest", params={"window": window})


@app.get("/system/autonomy/state")
async def system_autonomy_state(refresh: bool = False, _auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/system/autonomy/state", params={"refresh": refresh})


@app.get("/system/healing/incidents")
async def system_healing_incidents(limit: int = 50, _auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/system/healing/incidents", params={"limit": limit})


@app.get("/system/learning/summary")
async def system_learning_summary(refresh: bool = False, _auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/system/learning/summary", params={"refresh": refresh})


@app.get("/system/self-mod/state")
async def system_self_mod_state(_auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/system/self-mod/state")


@app.get("/system/self-mod/proposals")
async def system_self_mod_proposals(status: str | None = None, limit: int = 50, _auth: None = Depends(require_api_key)):
    return await _forward_get("http://run-ledger-service:8011", "/system/self-mod/proposals", params={"status": status, "limit": limit})


@app.post("/system/self-mod/generate")
async def system_self_mod_generate(
    refresh: bool = True,
    auto_apply: bool | None = None,
    _auth: None = Depends(require_role("admin")),
):
    return await _forward_post(
        "http://run-ledger-service:8011",
        "/system/self-mod/generate",
        params={"refresh": refresh, "auto_apply": auto_apply},
    )


@app.post("/system/self-mod/apply/{proposal_id}")
async def system_self_mod_apply(
    proposal_id: str,
    auto_applied: bool = False,
    _auth: None = Depends(require_role("admin")),
):
    return await _forward_post(
        "http://run-ledger-service:8011",
        f"/system/self-mod/apply/{proposal_id}",
        params={"auto_applied": auto_applied},
    )


@app.get("/admin/ui", response_class=HTMLResponse)
async def admin_official_ui(_auth: None = Depends(require_role("admin"))):
    return HTMLResponse(content=_load_html_template("official_ui.html"))


@app.get("/admin/data-quality")
async def admin_data_quality(_auth: None = Depends(require_role("admin"))):
    from apps.core.data_quality import run_quality_audit

    async with httpx.AsyncClient(timeout=20.0) as client:
        async def _safe(url: str, params: dict | None = None) -> dict:
            try:
                resp = await client.get(url, params=params, headers={"X-API-Key": settings.API_KEY})
                if resp.status_code >= 400:
                    return {}
                return resp.json()
            except Exception:
                return {}

        briefing, ann_stats, sentiment, analyst, patterns = await asyncio.gather(
            _safe(f"{settings.AGENT_A_SERVICE_URL}/briefings/latest"),
            _safe(f"{settings.AGENT_B_SERVICE_URL}/announcements/stats"),
            _safe(f"{settings.AGENT_C_SERVICE_URL}/sentiment/digest/latest"),
            _safe(f"{settings.AGENT_D_SERVICE_URL}/reports/latest", {"type": "daily"}),
            _safe(f"{settings.AGENT_E_SERVICE_URL}/patterns/summary"),
        )

    import yaml
    from pathlib import Path as _Path
    universe_tickers: set[str] = set()
    universe_path = _Path(__file__).resolve().parents[2] / "config" / "universe.yml"
    if universe_path.exists():
        with open(universe_path) as f:
            data = yaml.safe_load(f)
        for company in (data.get("companies") or []):
            if isinstance(company, dict) and company.get("ticker"):
                universe_tickers.add(str(company["ticker"]).upper())

    report = await run_quality_audit(
        briefing_latest=briefing,
        announcements_stats=ann_stats,
        sentiment_latest=sentiment,
        analyst_latest=analyst,
        patterns_summary=patterns,
        universe_tickers=universe_tickers or None,
    )
    return report.to_dict()
