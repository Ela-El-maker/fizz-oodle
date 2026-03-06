from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
import time
from typing import Any

from redis import ConnectionPool, Redis
from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedis

from apps.core.config import get_settings
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


_CACHE_LOCK = threading.Lock()
_SYNC_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_sync_pool: ConnectionPool | None = None
_async_pool: AsyncConnectionPool | None = None


def _get_sync_pool() -> ConnectionPool:
    global _sync_pool  # noqa: PLW0603
    if _sync_pool is None:
        _sync_pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
    return _sync_pool


def _get_async_pool() -> AsyncConnectionPool:
    global _async_pool  # noqa: PLW0603
    if _async_pool is None:
        _async_pool = AsyncConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
    return _async_pool


def _base_payload() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "agents": {}}


def _normalize(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = _base_payload()
    if not isinstance(payload, dict):
        return base
    agents = payload.get("agents")
    merged = {
        "version": int(payload.get("version") or 1),
        "updated_at": payload.get("updated_at"),
        "agents": agents if isinstance(agents, dict) else {},
    }
    return merged


def _loads(raw: str | bytes | None) -> dict[str, Any]:
    if not raw:
        return _base_payload()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    try:
        parsed = json.loads(text)
    except Exception:
        logger.warning("runtime_overrides_parse_failed", raw=text[:256])
        return _base_payload()
    return _normalize(parsed if isinstance(parsed, dict) else None)


def _key() -> str:
    return settings.RUNTIME_OVERRIDES_REDIS_KEY


def load_runtime_overrides_sync(*, force_refresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    ttl = max(1, int(settings.RUNTIME_OVERRIDES_CACHE_TTL_SECONDS))
    with _CACHE_LOCK:
        cached = _SYNC_CACHE.get("value")
        expires_at = float(_SYNC_CACHE.get("expires_at") or 0.0)
        if not force_refresh and cached is not None and now < expires_at:
            return deepcopy(cached)

    payload = _base_payload()
    try:
        client = Redis(connection_pool=_get_sync_pool())
        payload = _loads(client.get(_key()))
    except Exception as exc:
        logger.warning("runtime_overrides_sync_load_failed", error=str(exc))

    with _CACHE_LOCK:
        _SYNC_CACHE["value"] = payload
        _SYNC_CACHE["expires_at"] = now + ttl
    return deepcopy(payload)


def get_agent_overrides_sync(agent_name: str, *, force_refresh: bool = False) -> dict[str, Any]:
    payload = load_runtime_overrides_sync(force_refresh=force_refresh)
    agents = payload.get("agents") if isinstance(payload, dict) else {}
    if not isinstance(agents, dict):
        return {}
    agent_payload = agents.get(agent_name)
    return deepcopy(agent_payload) if isinstance(agent_payload, dict) else {}


async def load_runtime_overrides() -> dict[str, Any]:
    client = AsyncRedis(connection_pool=_get_async_pool())
    try:
        return _loads(await client.get(_key()))
    except Exception as exc:
        logger.warning("runtime_overrides_async_load_failed", error=str(exc))
        return _base_payload()


async def store_runtime_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize(payload)
    normalized["updated_at"] = datetime.now(timezone.utc).isoformat()
    client = AsyncRedis(connection_pool=_get_async_pool())
    await client.set(_key(), json.dumps(normalized))

    with _CACHE_LOCK:
        _SYNC_CACHE["value"] = deepcopy(normalized)
        _SYNC_CACHE["expires_at"] = time.monotonic() + max(1, int(settings.RUNTIME_OVERRIDES_CACHE_TTL_SECONDS))
    return normalized

