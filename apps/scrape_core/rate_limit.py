from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(slots=True)
class _DomainState:
    tokens: float
    last_refill: float
    multiplier: float


class AdaptiveDomainLimiter:
    def __init__(self) -> None:
        self._states: dict[str, _DomainState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, domain: str) -> asyncio.Lock:
        lock = self._locks.get(domain)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[domain] = lock
        return lock

    async def acquire(self, domain: str, base_rps: float) -> None:
        rate = max(0.01, float(base_rps))
        capacity = max(1.0, rate * 2)

        while True:
            async with self._lock(domain):
                now = time.monotonic()
                state = self._states.get(domain)
                if state is None:
                    state = _DomainState(tokens=capacity, last_refill=now, multiplier=1.0)
                    self._states[domain] = state

                effective_rate = max(0.01, rate * state.multiplier)
                elapsed = max(0.0, now - state.last_refill)
                state.tokens = min(capacity, state.tokens + elapsed * effective_rate)
                state.last_refill = now

                if state.tokens >= 1.0:
                    state.tokens -= 1.0
                    return

                wait = max(0.01, (1.0 - state.tokens) / effective_rate)

            await asyncio.sleep(wait)

    def record_response(self, domain: str, status_code: int | None = None, error_type: str | None = None) -> None:
        state = self._states.get(domain)
        if state is None:
            return
        if status_code in {429, 503} or error_type in {"rate_limited", "timeout", "upstream_5xx"}:
            state.multiplier = max(0.2, state.multiplier * 0.7)
            return
        if status_code and 200 <= status_code < 400:
            state.multiplier = min(2.0, state.multiplier + 0.05)


global_rate_limiter = AdaptiveDomainLimiter()
