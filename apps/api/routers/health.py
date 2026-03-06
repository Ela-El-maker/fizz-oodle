from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
import httpx
from redis.asyncio import Redis
from sqlalchemy import text, select

from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.models import AgentRun

settings = get_settings()
router = APIRouter()


KNOWN_AGENTS = ("system", "announcements", "briefing", "sentiment", "analyst", "archivist", "narrator")
AGENT_LABELS = {
    "agent_a": "briefing",
    "agent_b": "announcements",
    "agent_c": "sentiment",
    "agent_d": "analyst",
    "agent_e": "archivist",
    "agent_f": "narrator",
}


async def _check_db() -> dict:
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "fail", "error": str(e)}


async def _check_redis() -> dict:
    try:
        client = Redis.from_url(settings.REDIS_URL)
        try:
            pong = await client.ping()
        finally:
            await client.aclose()
        return {"status": "ok" if pong else "fail"}
    except Exception as e:
        return {"status": "fail", "error": str(e)}


async def _check_ollama() -> dict:
    llm_mode = (settings.LLM_MODE or "off").lower()
    if llm_mode == "off":
        return {"status": "off"}

    if llm_mode == "api":
        base_url = (settings.LLM_API_BASE_URL or "").strip()
        api_key = (settings.LLM_API_KEY or "").strip()
        if not base_url:
            return {"status": "fail", "mode": "api", "error": "LLM_API_BASE_URL is empty"}
        if not api_key:
            return {"status": "fail", "mode": "api", "error": "LLM_API_KEY is empty"}

        # Default Stage-1 behavior is non-billing-safe config validation only.
        # Enable LLM_HEALTHCHECK_NETWORK=true to perform an actual provider request.
        if not settings.LLM_HEALTHCHECK_NETWORK:
            return {
                "status": "ok",
                "mode": "api",
                "provider": settings.LLM_PROVIDER,
                "base_url": base_url,
                "model": settings.LLM_MODEL,
                "check": "configured",
            }

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if 200 <= resp.status_code < 300:
                return {
                    "status": "ok",
                    "mode": "api",
                    "provider": settings.LLM_PROVIDER,
                    "base_url": base_url,
                    "model": settings.LLM_MODEL,
                    "check": "network",
                }
            return {
                "status": "fail",
                "mode": "api",
                "provider": settings.LLM_PROVIDER,
                "error": f"http_{resp.status_code}",
            }
        except Exception as e:
            return {"status": "fail", "mode": "api", "provider": settings.LLM_PROVIDER, "error": str(e)}

    if llm_mode != "local":
        return {"status": "fail", "error": f"Unsupported LLM_MODE: {llm_mode}"}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if 200 <= resp.status_code < 300:
                return {"status": "ok"}
            return {"status": "fail", "error": f"http_{resp.status_code}"}
    except Exception as e:
        return {"status": "fail", "error": str(e)}


async def _last_runs() -> dict:
    output = {name: {"status": "never_run", "run_id": None, "started_at": None, "finished_at": None} for name in KNOWN_AGENTS}

    try:
        async with get_session() as session:
            for name in KNOWN_AGENTS:
                row = (
                    await session.execute(
                        select(AgentRun).where(AgentRun.agent_name == name).order_by(AgentRun.started_at.desc()).limit(1)
                    )
                ).scalar_one_or_none()
                if row is None:
                    continue
                output[name] = {
                    "status": row.status,
                    "run_id": str(row.run_id),
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                }
    except Exception as e:
        for name in KNOWN_AGENTS:
            output[name] = {"status": "unknown", "run_id": None, "started_at": None, "finished_at": None, "error": str(e)}

    return output


@router.get("/health")
async def health():
    db = await _check_db()
    redis = await _check_redis()
    ollama = await _check_ollama()
    runs = await _last_runs()

    overall = "ok"
    failed = [dep for dep in (db, redis) if dep["status"] == "fail"]
    if len(failed) == 1:
        overall = "degraded"
    elif len(failed) == 2:
        overall = "fail"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "api": {"status": "ok"},
        "dependencies": {
            "postgres": db,
            "redis": redis,
            "llm": ollama,
            "ollama": ollama,
        },
        "agents": {
            agent_label: runs.get(run_name, {"status": "never_run", "run_id": None, "started_at": None, "finished_at": None})
            for agent_label, run_name in AGENT_LABELS.items()
        },
        "runs": runs,
    }
