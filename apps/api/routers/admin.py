from __future__ import annotations

from datetime import date, timedelta
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from celery_app import celery_app
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.models import AgentRun, Announcement, SourceHealth
from apps.core.run_service import start_run

settings = get_settings()


def require_admin_api_key(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
) -> None:
    expected = settings.API_KEY
    if not expected:
        return
    if x_api_key == expected:
        return
    if api_key == expected:
        return
    raise HTTPException(status_code=401, detail="Invalid API key")


router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin_api_key)])


@router.get("/admin/announcements", response_class=HTMLResponse)
async def admin_announcements(
    api_key: str | None = Query(default=None),
    ticker: str | None = None,
    type: str | None = None,  # noqa: A002
    source_id: str | None = None,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    alerted: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    async with get_session() as session:
        stmt = select(Announcement).order_by(Announcement.first_seen_at.desc()).limit(limit)
        if ticker:
            stmt = stmt.where(Announcement.ticker == ticker.upper())
        if type:
            stmt = stmt.where(Announcement.announcement_type == type)
        if source_id:
            stmt = stmt.where(Announcement.source_id == source_id)
        if date_from:
            stmt = stmt.where(Announcement.announcement_date >= date_from)
        if date_to:
            stmt = stmt.where(Announcement.announcement_date < (date_to + timedelta(days=1)))
        if alerted is not None:
            stmt = stmt.where(Announcement.alerted.is_(alerted))

        rows = (await session.execute(stmt)).scalars().all()

        latest_run = (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.agent_name == "announcements")
                .order_by(AgentRun.started_at.desc())
                .limit(1)
            )
        ).scalars().first()

        health_rows = (await session.execute(select(SourceHealth).order_by(SourceHealth.source_id.asc()))).scalars().all()

    run_metrics = latest_run.metrics if latest_run else {}

    html = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Admin · Announcements</title>",
        "<style>body{font-family:system-ui;margin:20px;background:#f5f7fb}.card{background:#fff;border:1px solid #e7eaf0;border-radius:10px;padding:14px;margin-bottom:14px}.row{display:flex;gap:8px;flex-wrap:wrap}.pill{padding:2px 8px;border-radius:999px;background:#eef}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #eee;padding:8px;text-align:left;font-size:13px}a{color:#2563eb;text-decoration:none}</style>",
        "</head><body>",
        "<h1>Announcements Admin</h1>",
        "<div class='card'><form method='get' class='row'>",
        f"<input name='ticker' placeholder='ticker' value='{ticker or ''}' />",
        f"<input name='type' placeholder='type' value='{type or ''}' />",
        f"<input name='source_id' placeholder='source_id' value='{source_id or ''}' />",
        f"<input name='date_from' type='date' value='{date_from.isoformat() if date_from else ''}' />",
        f"<input name='date_to' type='date' value='{date_to.isoformat() if date_to else ''}' />",
        f"<select name='alerted'><option value='' {'selected' if alerted is None else ''}>alerted:any</option><option value='true' {'selected' if alerted is True else ''}>true</option><option value='false' {'selected' if alerted is False else ''}>false</option></select>",
        f"<input name='limit' type='number' value='{limit}' min='1' max='200' />",
        "<button type='submit'>Filter</button>",
        "</form>",
        f"<form method='post' action='/admin/announcements/trigger?api_key={api_key or ''}' style='margin-top:10px'>",
        "<button type='submit'>Trigger Agent B Now</button>",
        "</form></div>",
    ]

    if latest_run:
        html.append("<div class='card'><h3>Latest Agent B Run</h3>")
        html.append(f"<div>Status: <span class='pill'>{latest_run.status}</span> · Run ID: {latest_run.run_id}</div>")
        html.append(f"<div>Started: {latest_run.started_at} · Finished: {latest_run.finished_at}</div>")
        html.append("<pre style='white-space:pre-wrap'>" + json.dumps(run_metrics, indent=2, default=str) + "</pre></div>")

    html.append("<div class='card'><h3>Source Health</h3><table><thead><tr><th>source_id</th><th>breaker</th><th>failures</th><th>cooldown_until</th><th>last_error/metrics</th></tr></thead><tbody>")
    for row in health_rows:
        html.append(
            "<tr>"
            f"<td>{row.source_id}</td>"
            f"<td>{row.breaker_state}</td>"
            f"<td>{row.consecutive_failures}</td>"
            f"<td>{row.cooldown_until or ''}</td>"
            f"<td><pre style='white-space:pre-wrap'>{json.dumps(row.last_metrics, default=str)}</pre></td>"
            "</tr>"
        )
    html.append("</tbody></table></div>")

    html.append("<div class='card'><h3>Announcements</h3><table><thead><tr><th>id</th><th>ticker</th><th>type</th><th>headline</th><th>source</th><th>alerted</th><th>date</th></tr></thead><tbody>")
    for row in rows:
        html.append(
            "<tr>"
            f"<td style='font-family:monospace'>{row.announcement_id[:10]}…</td>"
            f"<td>{row.ticker or ''}</td>"
            f"<td>{row.announcement_type}</td>"
            f"<td><a href='{row.url}'>{row.headline}</a></td>"
            f"<td>{row.source_id}</td>"
            f"<td>{row.alerted}</td>"
            f"<td>{row.announcement_date or ''}</td>"
            "</tr>"
        )
    html.append("</tbody></table></div>")

    html.append("</body></html>")
    return "".join(html)


@router.post("/admin/announcements/trigger")
async def admin_trigger_announcements(_auth: None = Depends(require_admin_api_key)):
    run_id = await start_run("announcements")
    celery_app.send_task("agent_announcements.run", kwargs={"run_id": run_id})
    return {"ok": True, "run_id": run_id}
