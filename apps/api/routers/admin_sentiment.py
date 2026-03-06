from __future__ import annotations

from datetime import date
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select

from celery_app import celery_app
from apps.agents.sentiment.registry import get_all_source_configs, get_source_configs
from apps.api.routers.admin import require_admin_api_key
from apps.core.database import get_session
from apps.core.models import AgentRun, SentimentDigestReport, SentimentRawPost, SentimentWeekly, SourceHealth
from apps.core.run_service import start_run

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin_api_key)])


@router.get("/admin/sentiment", response_class=HTMLResponse)
async def admin_sentiment(
    api_key: str | None = Query(default=None),
    week_start: date | None = Query(default=None),
    ticker: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    enabled = {src.source_id for src in get_source_configs()}
    configs = {src.source_id: src for src in get_all_source_configs()}
    async with get_session() as session:
        latest_run = (
            await session.execute(
                select(AgentRun).where(AgentRun.agent_name == "sentiment").order_by(AgentRun.started_at.desc()).limit(1)
            )
        ).scalars().first()

        if week_start is None:
            week_start = (
                await session.execute(select(SentimentWeekly.week_start).order_by(desc(SentimentWeekly.week_start)).limit(1))
            ).scalar_one_or_none()

        weekly_stmt = select(SentimentWeekly).order_by(SentimentWeekly.ticker.asc()).limit(limit)
        if week_start:
            weekly_stmt = weekly_stmt.where(SentimentWeekly.week_start == week_start)
        if ticker:
            weekly_stmt = weekly_stmt.where(SentimentWeekly.ticker == ticker.upper())
        weekly_rows = (await session.execute(weekly_stmt)).scalars().all()

        raw_stmt = select(SentimentRawPost).order_by(SentimentRawPost.fetched_at.desc()).limit(limit)
        if source_id:
            raw_stmt = raw_stmt.where(SentimentRawPost.source_id == source_id)
        raw_rows = (await session.execute(raw_stmt)).scalars().all()

        source_health_rows = (
            await session.execute(
                select(SourceHealth).where(SourceHealth.source_id.in_(tuple(configs.keys()))).order_by(SourceHealth.source_id.asc())
            )
        ).scalars().all()
        source_health = {row.source_id: row for row in source_health_rows}

        latest_digest = (
            await session.execute(select(SentimentDigestReport).order_by(desc(SentimentDigestReport.week_start)).limit(1))
        ).scalars().first()

    html = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Admin · Sentiment</title>",
        "<style>body{font-family:system-ui;margin:20px;background:#f5f7fb}.card{background:#fff;border:1px solid #e7eaf0;border-radius:10px;padding:14px;margin-bottom:14px}.row{display:flex;gap:8px;flex-wrap:wrap}.pill{padding:2px 8px;border-radius:999px;background:#eef}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #eee;padding:8px;text-align:left;font-size:13px}a{color:#2563eb;text-decoration:none}pre{white-space:pre-wrap}</style>",
        "</head><body>",
        "<h1>Sentiment Admin</h1>",
        "<div class='card'><form method='get' class='row'>",
        f"<input name='week_start' type='date' value='{week_start.isoformat() if week_start else ''}' />",
        f"<input name='ticker' placeholder='ticker' value='{ticker or ''}' />",
        f"<input name='source_id' placeholder='source_id' value='{source_id or ''}' />",
        f"<input name='limit' type='number' value='{limit}' min='1' max='200' />",
        "<button type='submit'>Filter</button>",
        "</form>",
        f"<form method='post' action='/admin/sentiment/trigger?api_key={api_key or ''}' style='margin-top:10px'>",
        "<button type='submit'>Trigger Agent C Now</button>",
        "</form>",
        f"<form method='post' action='/admin/sentiment/resend?api_key={api_key or ''}' style='margin-top:10px'>",
        f"<input name='week_start' type='date' value='{week_start.isoformat() if week_start else ''}' />",
        "<button type='submit'>Force Resend Digest</button>",
        "</form></div>",
    ]

    if latest_run:
        html.append("<div class='card'><h3>Latest Agent C Run</h3>")
        html.append(f"<div>Status: <span class='pill'>{latest_run.status}</span> · Run ID: {latest_run.run_id}</div>")
        html.append(f"<div>Started: {latest_run.started_at} · Finished: {latest_run.finished_at}</div>")
        html.append("<pre>" + json.dumps(latest_run.metrics or {}, indent=2, default=str) + "</pre></div>")

    if latest_digest:
        html.append("<div class='card'><h3>Latest Digest</h3>")
        html.append(
            f"<div>Week: {latest_digest.week_start} · Status: <span class='pill'>{latest_digest.status}</span> · "
            f"Sent: {latest_digest.email_sent_at or ''}</div>"
        )
        if latest_digest.email_error:
            html.append(f"<div>Email Error: {latest_digest.email_error}</div>")
        html.append("</div>")

    html.append("<div class='card'><h3>Sentiment Sources Health</h3><table><thead><tr><th>source_id</th><th>enabled</th><th>breaker</th><th>failures</th><th>cooldown</th><th>last_metrics</th></tr></thead><tbody>")
    for source_id, config in sorted(configs.items()):
        row = source_health.get(source_id)
        html.append(
            "<tr>"
            f"<td>{source_id}</td>"
            f"<td>{source_id in enabled}</td>"
            f"<td>{(row.breaker_state if row else 'closed')}</td>"
            f"<td>{(row.consecutive_failures if row else 0)}</td>"
            f"<td>{(row.cooldown_until if row else '')}</td>"
            f"<td><pre>{json.dumps((row.last_metrics if row else {'weight': config.weight}), default=str)}</pre></td>"
            "</tr>"
        )
    html.append("</tbody></table></div>")

    html.append(
        "<div class='card'><h3>Weekly Sentiment</h3><table><thead><tr><th>ticker</th><th>company</th><th>mentions</th><th>bull%</th><th>bear%</th><th>neutral%</th><th>score</th><th>confidence</th><th>wow</th></tr></thead><tbody>"
    )
    for row in weekly_rows:
        html.append(
            "<tr>"
            f"<td>{row.ticker}</td>"
            f"<td>{row.company_name}</td>"
            f"<td>{row.mentions_count}</td>"
            f"<td>{float(row.bullish_pct):.2f}</td>"
            f"<td>{float(row.bearish_pct):.2f}</td>"
            f"<td>{float(row.neutral_pct):.2f}</td>"
            f"<td>{float(row.weighted_score):.3f}</td>"
            f"<td>{float(row.confidence):.3f}</td>"
            f"<td>{(float(row.wow_delta) if row.wow_delta is not None else '')}</td>"
            "</tr>"
        )
    html.append("</tbody></table></div>")

    html.append("<div class='card'><h3>Raw Posts (latest)</h3><table><thead><tr><th>source_id</th><th>title</th><th>published</th><th>url</th></tr></thead><tbody>")
    for row in raw_rows:
        title = row.title or row.content[:120]
        link = row.url or "#"
        html.append(
            "<tr>"
            f"<td>{row.source_id}</td>"
            f"<td>{title}</td>"
            f"<td>{row.published_at or ''}</td>"
            f"<td><a href='{link}'>link</a></td>"
            "</tr>"
        )
    html.append("</tbody></table></div></body></html>")

    return "".join(html)


@router.post("/admin/sentiment/trigger")
async def admin_trigger_sentiment(_auth: None = Depends(require_admin_api_key)):
    run_id = await start_run("sentiment")
    celery_app.send_task("agent_sentiment.run", kwargs={"run_id": run_id})
    return {"ok": True, "run_id": run_id}


@router.post("/admin/sentiment/resend")
async def admin_resend_sentiment(
    week_start: date | None = None,
    force: bool = True,
    _auth: None = Depends(require_admin_api_key),
):
    target_week = week_start
    if target_week is None:
        async with get_session() as session:
            target_week = (
                await session.execute(select(SentimentDigestReport.week_start).order_by(desc(SentimentDigestReport.week_start)).limit(1))
            ).scalar_one_or_none()
    if target_week is None:
        target_week = date.today()

    run_id = await start_run("sentiment")
    celery_app.send_task(
        "agent_sentiment.run",
        kwargs={
            "run_id": run_id,
            "week_start": target_week.isoformat(),
            "force_send": bool(force),
        },
    )
    return {"ok": True, "run_id": run_id, "week_start": target_week.isoformat(), "force": bool(force)}


@router.post("/admin/sentiment/sources/reset")
async def admin_reset_sentiment_source_health(
    source_id: str | None = None,
    _auth: None = Depends(require_admin_api_key),
):
    async with get_session() as session:
        stmt = select(SourceHealth)
        if source_id:
            stmt = stmt.where(SourceHealth.source_id == source_id)
        rows = (await session.execute(stmt)).scalars().all()

        for row in rows:
            row.consecutive_failures = 0
            row.breaker_state = "closed"
            row.cooldown_until = None
            metrics = dict(row.last_metrics or {})
            metrics["reset"] = True
            row.last_metrics = metrics

        await session.commit()

    return {"ok": True, "reset_count": len(rows), "source_id": source_id}
