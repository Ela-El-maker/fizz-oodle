from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from apps.core.config import get_settings
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class _DomainGate:
    last_ts: float = 0.0


_domain_gates: dict[str, _DomainGate] = {}


async def _throttle(url: str) -> None:
    domain = urlparse(url).netloc
    gate = _domain_gates.setdefault(domain, _DomainGate())
    now = time.time()
    wait = max(0.0, gate.last_ts + settings.PER_DOMAIN_MIN_DELAY_SECONDS - now)
    if wait > 0:
        await asyncio.sleep(wait)
    gate.last_ts = time.time()


async def fetch_text(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    timeout_secs: int | None = None,
) -> str:
    await _throttle(url)
    timeout = httpx.Timeout(timeout_secs if timeout_secs is not None else settings.REQUEST_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.text
