from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class _Entry:
    etag: str | None = None
    last_modified: str | None = None
    updated_at: datetime | None = None
    not_modified_count: int = 0


class FetchCacheState:
    def __init__(self) -> None:
        self._state: dict[str, _Entry] = {}

    def conditional_headers(self, key: str, *, ttl_seconds: int = 0) -> dict[str, str]:
        entry = self._state.get(key)
        if entry is None:
            return {}
        if ttl_seconds > 0 and entry.updated_at is not None:
            if entry.updated_at < datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds):
                return {}
        headers: dict[str, str] = {}
        if entry.etag:
            headers["If-None-Match"] = entry.etag
        if entry.last_modified:
            headers["If-Modified-Since"] = entry.last_modified
        return headers

    def record_response(self, key: str, *, etag: str | None, last_modified: str | None) -> None:
        entry = self._state.get(key)
        if entry is None:
            entry = _Entry()
            self._state[key] = entry
        if etag:
            entry.etag = etag
        if last_modified:
            entry.last_modified = last_modified
        entry.updated_at = datetime.now(timezone.utc)
        entry.not_modified_count = 0

    def record_not_modified(self, key: str) -> int:
        entry = self._state.get(key)
        if entry is None:
            entry = _Entry(updated_at=datetime.now(timezone.utc), not_modified_count=1)
            self._state[key] = entry
            return 1
        entry.updated_at = datetime.now(timezone.utc)
        entry.not_modified_count += 1
        return entry.not_modified_count

    def get_not_modified_count(self, key: str) -> int:
        entry = self._state.get(key)
        return entry.not_modified_count if entry else 0


global_fetch_cache = FetchCacheState()
