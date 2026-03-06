"""Per-source health scoring for the scrape pipeline.

Tracks success/failure/latency history over a rolling window and
computes a 0.0-1.0 health score per source_id.  Used by the healing
engine, data-quality audit, and operator dashboards.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _Event:
    ts: float
    ok: bool
    latency_ms: float
    error_type: str | None


@dataclass
class SourceHealth:
    source_id: str
    total: int = 0
    successes: int = 0
    failures: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    score: float = 1.0
    last_error: str | None = None
    last_success_ts: float | None = None


class SourceHealthTracker:
    """Rolling-window health tracker for scrape sources."""

    def __init__(self, window_seconds: int = 3600, max_events: int = 500) -> None:
        self._window = max(60, window_seconds)
        self._max = max(10, max_events)
        self._sources: dict[str, deque[_Event]] = {}

    def record(
        self,
        source_id: str,
        *,
        ok: bool,
        latency_ms: float = 0.0,
        error_type: str | None = None,
    ) -> None:
        """Record one fetch attempt for a source."""
        buf = self._sources.get(source_id)
        if buf is None:
            buf = deque(maxlen=self._max)
            self._sources[source_id] = buf
        buf.append(_Event(ts=time.monotonic(), ok=ok, latency_ms=latency_ms, error_type=error_type))

    def _prune(self, buf: deque[_Event]) -> list[_Event]:
        cutoff = time.monotonic() - self._window
        return [e for e in buf if e.ts >= cutoff]

    def health(self, source_id: str) -> SourceHealth:
        """Compute current health score for a source."""
        buf = self._sources.get(source_id)
        if not buf:
            return SourceHealth(source_id=source_id)

        events = self._prune(buf)
        if not events:
            return SourceHealth(source_id=source_id)

        total = len(events)
        successes = sum(1 for e in events if e.ok)
        failures = total - successes
        latencies = sorted(e.latency_ms for e in events if e.ok and e.latency_ms > 0)
        avg_lat = (sum(latencies) / len(latencies)) if latencies else 0.0
        p95_lat = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

        # Score components
        success_rate = successes / total if total > 0 else 0.0
        latency_penalty = min(1.0, avg_lat / 10000.0)  # 10s = full penalty
        recency_bonus = 0.0
        last_success_ts = None
        for e in reversed(events):
            if e.ok:
                last_success_ts = e.ts
                recency_bonus = 0.1
                break

        score = max(0.0, min(1.0, success_rate * 0.7 + (1.0 - latency_penalty) * 0.2 + recency_bonus))

        last_err = None
        for e in reversed(events):
            if not e.ok and e.error_type:
                last_err = e.error_type
                break

        return SourceHealth(
            source_id=source_id,
            total=total,
            successes=successes,
            failures=failures,
            avg_latency_ms=round(avg_lat, 1),
            p95_latency_ms=round(p95_lat, 1),
            score=round(score, 3),
            last_error=last_err,
            last_success_ts=last_success_ts,
        )

    def all_sources(self) -> list[SourceHealth]:
        """Return health for all tracked sources, sorted worst-first."""
        results = [self.health(sid) for sid in self._sources]
        results.sort(key=lambda h: h.score)
        return results

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable overview of all source health."""
        sources = self.all_sources()
        return {
            "total_sources": len(sources),
            "healthy": sum(1 for s in sources if s.score >= 0.7),
            "degraded": sum(1 for s in sources if 0.3 <= s.score < 0.7),
            "unhealthy": sum(1 for s in sources if s.score < 0.3),
            "sources": [
                {
                    "source_id": s.source_id,
                    "score": s.score,
                    "total": s.total,
                    "successes": s.successes,
                    "failures": s.failures,
                    "avg_latency_ms": s.avg_latency_ms,
                    "p95_latency_ms": s.p95_latency_ms,
                    "last_error": s.last_error,
                }
                for s in sources
            ],
        }


# Module-level singleton for use across the scrape pipeline
_tracker: SourceHealthTracker | None = None


def get_source_health_tracker(window_seconds: int = 3600) -> SourceHealthTracker:
    global _tracker
    if _tracker is None:
        _tracker = SourceHealthTracker(window_seconds=window_seconds)
    return _tracker
