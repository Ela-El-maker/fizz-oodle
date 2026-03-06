from __future__ import annotations

from datetime import date
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select

from celery_app import celery_app
from apps.api.routers.admin import require_admin_api_key
from apps.core.database import get_session
from apps.core.models import AgentRun, AnalystReport
from apps.core.run_service import start_run

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin_api_key)])


@router.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports(
    api_key: str | None = Query(default=None),
    report_type: str | None = Query(default=None),
    period_from: date | None = Query(default=None),
    period_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    async with get_session() as session:
        latest_run = (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.agent_name == "analyst")
                .order_by(AgentRun.started_at.desc())
                .limit(1)
            )
        ).scalars().first()

        stmt = select(AnalystReport)
        if report_type:
            stmt = stmt.where(AnalystReport.report_type == report_type)
        if period_from:
            stmt = stmt.where(AnalystReport.period_key >= period_from)
        if period_to:
            stmt = stmt.where(AnalystReport.period_key <= period_to)

        reports = (
            await session.execute(
                stmt.order_by(desc(AnalystReport.period_key), desc(AnalystReport.generated_at)).limit(limit)
            )
        ).scalars().all()

    html = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Admin · Reports</title>",
        "<style>body{font-family:system-ui;margin:20px;background:#f5f7fb}.card{background:#fff;border:1px solid #e7eaf0;border-radius:10px;padding:14px;margin-bottom:14px}.row{display:flex;gap:8px;flex-wrap:wrap}.pill{padding:2px 8px;border-radius:999px;background:#eef}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #eee;padding:8px;text-align:left;font-size:13px}a{color:#2563eb;text-decoration:none}pre{white-space:pre-wrap}</style>",
        "</head><body>",
        "<h1>Analyst Reports Admin</h1>",
        "<div class='card'><form method='get' class='row'>",
        f"<input name='report_type' placeholder='daily|weekly' value='{report_type or ''}' />",
        f"<input name='period_from' type='date' value='{period_from.isoformat() if period_from else ''}' />",
        f"<input name='period_to' type='date' value='{period_to.isoformat() if period_to else ''}' />",
        f"<input name='limit' type='number' value='{limit}' min='1' max='200' />",
        "<button type='submit'>Filter</button>",
        "</form>",
        f"<form method='post' action='/admin/reports/trigger?api_key={api_key or ''}' style='margin-top:10px'>",
        "<input name='report_type' placeholder='daily|weekly' value='daily' />",
        "<input name='period_key' type='date' />",
        "<button type='submit'>Trigger Analyst</button>",
        "</form>",
        f"<form method='post' action='/admin/reports/resend?api_key={api_key or ''}' style='margin-top:10px'>",
        "<input name='report_type' placeholder='daily|weekly' value='daily' />",
        "<input name='period_key' type='date' />",
        "<input name='force' value='true' />",
        "<button type='submit'>Force Resend</button>",
        "</form></div>",
    ]

    if latest_run:
        html.append("<div class='card'><h3>Latest Agent D Run</h3>")
        html.append(
            f"<div>Status: <span class='pill'>{latest_run.status}</span> · Run ID: {latest_run.run_id}</div>"
        )
        html.append(f"<div>Started: {latest_run.started_at} · Finished: {latest_run.finished_at}</div>")
        html.append("<pre>" + json.dumps(latest_run.metrics or {}, indent=2, default=str) + "</pre></div>")

    html.append("<div class='card'><h3>Reports</h3><table><thead><tr><th>period</th><th>type</th><th>status</th><th>subject</th><th>degraded</th><th>sent</th></tr></thead><tbody>")
    for row in reports:
        html.append(
            "<tr>"
            f"<td>{row.period_key}</td>"
            f"<td>{row.report_type}</td>"
            f"<td>{row.status}</td>"
            f"<td>{row.subject}</td>"
            f"<td>{row.degraded}</td>"
            f"<td>{row.email_sent_at or ''}</td>"
            "</tr>"
        )
    html.append("</tbody></table></div></body></html>")

    return "".join(html)


@router.post("/admin/reports/trigger")
async def admin_trigger_reports(
    report_type: str = "daily",
    period_key: date | None = None,
    _auth: None = Depends(require_admin_api_key),
):
    normalized_type = report_type.strip().lower()
    run_id = await start_run("analyst")
    celery_app.send_task(
        "agent_analyst.run",
        kwargs={
            "run_id": run_id,
            "report_type": normalized_type,
            "period_key": period_key.isoformat() if period_key else None,
        },
    )
    return {
        "ok": True,
        "run_id": run_id,
        "report_type": normalized_type,
        "period_key": period_key.isoformat() if period_key else None,
    }


@router.post("/admin/reports/resend")
async def admin_resend_reports(
    report_type: str = "daily",
    period_key: date | None = None,
    force: bool = True,
    _auth: None = Depends(require_admin_api_key),
):
    normalized_type = report_type.strip().lower()
    run_id = await start_run("analyst")
    celery_app.send_task(
        "agent_analyst.run",
        kwargs={
            "run_id": run_id,
            "report_type": normalized_type,
            "period_key": period_key.isoformat() if period_key else None,
            "force_send": bool(force),
        },
    )
    return {
        "ok": True,
        "run_id": run_id,
        "report_type": normalized_type,
        "period_key": period_key.isoformat() if period_key else None,
        "force": bool(force),
    }
