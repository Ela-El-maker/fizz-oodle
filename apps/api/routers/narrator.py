from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.agents.narrator.monitor import (
    build_monitor_snapshot,
    get_monitor_cycles,
    get_monitor_events,
    get_monitor_health,
    get_monitor_pipeline,
    get_monitor_requests,
    get_monitor_scrapers,
    get_monitor_status,
)
from apps.agents.narrator.pipeline import (
    get_or_build_announcement_insight,
    get_or_build_story,
    get_story_by_card_id,
    list_stories,
    refresh_announcement_context,
    run_narrator_pipeline,
)
from apps.api.routers.auth import require_api_key
from apps.core.database import get_session

router = APIRouter(tags=["narrator"], dependencies=[Depends(require_api_key)])


@router.get("/stories/latest")
async def stories_latest(
    scope: str = "market",
    context: str = "prices",
    ticker: str | None = None,
    force_regenerate: bool = False,
):
    async with get_session() as session:
        item, meta = await get_or_build_story(
            session,
            scope=scope,
            context=context,
            ticker=ticker,
            force_regenerate=force_regenerate,
        )
        await session.commit()
    return {"item": item, "meta": meta}


@router.get("/stories")
async def stories_list(
    scope: str | None = None,
    ticker: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    async with get_session() as session:
        items = await list_stories(session, scope=scope, ticker=ticker, status=status, limit=limit, offset=offset)
    return {"items": items, "limit": max(1, min(limit, 200)), "offset": max(0, offset)}


@router.get("/stories/{card_id}")
async def stories_get(card_id: str):
    async with get_session() as session:
        item = await get_story_by_card_id(session, card_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"item": item}


@router.get("/announcements/{announcement_id}/insight")
async def narrator_announcement_insight(
    announcement_id: str,
    refresh_context_if_needed: bool = True,
    force_regenerate: bool = False,
):
    async with get_session() as session:
        payload, meta = await get_or_build_announcement_insight(
            session,
            announcement_id,
            refresh_context_if_needed=refresh_context_if_needed,
            force_regenerate=force_regenerate,
        )
        await session.commit()
    return {"announcement_id": announcement_id, "item": payload, "meta": meta}


@router.post("/announcements/{announcement_id}/context/refresh")
async def narrator_announcement_context_refresh(announcement_id: str):
    async with get_session() as session:
        refresh = await refresh_announcement_context(session, announcement_id)
        await session.commit()
    return {"announcement_id": announcement_id, "refresh": refresh}


@router.post("/stories/rebuild")
async def narrator_rebuild(force_regenerate: bool = True):
    result = await run_narrator_pipeline(force_regenerate=force_regenerate)
    return {"accepted": True, "result": result}


@router.get("/stories/monitor/status")
async def stories_monitor_status(window_minutes: int = 30):
    async with get_session() as session:
        item = await get_monitor_status(session, window_minutes=window_minutes)
    return item


@router.get("/stories/monitor/pipeline")
async def stories_monitor_pipeline(window_minutes: int = 30):
    async with get_session() as session:
        item = await get_monitor_pipeline(session, window_minutes=window_minutes)
    return item


@router.get("/stories/monitor/requests")
async def stories_monitor_requests(limit: int = 20, window_minutes: int = 30):
    async with get_session() as session:
        item = await get_monitor_requests(session, limit=limit, window_minutes=window_minutes)
    return item


@router.get("/stories/monitor/scrapers")
async def stories_monitor_scrapers(window_minutes: int = 30):
    async with get_session() as session:
        item = await get_monitor_scrapers(session, window_minutes=window_minutes)
    return item


@router.get("/stories/monitor/events")
async def stories_monitor_events(limit: int = 20, window_minutes: int = 30):
    async with get_session() as session:
        item = await get_monitor_events(session, limit=limit, window_minutes=window_minutes)
    return item


@router.get("/stories/monitor/cycles")
async def stories_monitor_cycles(limit: int = 5, window_minutes: int = 30):
    async with get_session() as session:
        item = await get_monitor_cycles(session, limit=limit, window_minutes=window_minutes)
    return item


@router.get("/stories/monitor/health")
async def stories_monitor_health(window_minutes: int = 30):
    async with get_session() as session:
        item = await get_monitor_health(session, window_minutes=window_minutes)
    return item


@router.get("/stories/monitor/snapshot")
async def stories_monitor_snapshot(window_minutes: int = 30, events_limit: int = 20, cycles_limit: int = 5):
    async with get_session() as session:
        snapshot = await build_monitor_snapshot(
            session,
            window_minutes=window_minutes,
            events_limit=events_limit,
            cycles_limit=cycles_limit,
        )
    return snapshot
