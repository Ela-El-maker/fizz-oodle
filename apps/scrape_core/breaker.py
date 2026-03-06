from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class BreakerState:
    state: str = "closed"
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None


class SimpleCircuitBreaker:
    def __init__(self, fail_threshold: int = 5, cooldown_minutes: int = 60) -> None:
        self.fail_threshold = max(1, int(fail_threshold))
        self.cooldown_minutes = max(1, int(cooldown_minutes))
        self._state = BreakerState()

    def allow(self, now_utc: datetime | None = None) -> bool:
        now = now_utc or datetime.now(timezone.utc)
        if self._state.state != "open":
            return True
        if self._state.cooldown_until is None:
            return False
        if self._state.cooldown_until <= now:
            self._state.state = "half_open"
            self._state.consecutive_failures = 0
            self._state.cooldown_until = None
            return True
        return False

    def record_success(self) -> None:
        self._state.consecutive_failures = 0
        self._state.state = "closed"
        self._state.cooldown_until = None

    def record_failure(self) -> None:
        self._state.consecutive_failures += 1
        if self._state.consecutive_failures >= self.fail_threshold:
            self._state.state = "open"
            self._state.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.cooldown_minutes)

    @property
    def snapshot(self) -> BreakerState:
        return BreakerState(
            state=self._state.state,
            consecutive_failures=self._state.consecutive_failures,
            cooldown_until=self._state.cooldown_until,
        )
