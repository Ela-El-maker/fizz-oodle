from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.agents.archivist import pipeline as archivist_pipeline


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _RowsResult(self._rows)


@pytest.mark.asyncio
async def test_pattern_lifecycle_promotes_and_retires(monkeypatch) -> None:
    rows = [
        SimpleNamespace(
            status="candidate",
            active=True,
            occurrence_count=8,
            accuracy_pct=80.0,
            updated_at=datetime.now(timezone.utc),
        ),
        SimpleNamespace(
            status="confirmed",
            active=True,
            occurrence_count=12,
            accuracy_pct=30.0,
            updated_at=datetime.now(timezone.utc),
        ),
    ]
    session = _Session(rows)

    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM", 5)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_PROMOTION_THRESHOLD_PCT", 65.0)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_MIN_OCCURRENCES_FOR_RETIRE", 8)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_RETIRE_THRESHOLD_PCT", 45.0)

    changed = await archivist_pipeline._apply_pattern_lifecycle(session)
    assert changed == 2
    assert rows[0].status == "confirmed"
    assert rows[0].active is True
    assert rows[1].status == "retired"
    assert rows[1].active is False


@pytest.mark.asyncio
async def test_pattern_lifecycle_no_changes_when_threshold_not_met(monkeypatch) -> None:
    rows = [
        SimpleNamespace(
            status="candidate",
            active=True,
            occurrence_count=2,
            accuracy_pct=90.0,
            updated_at=datetime.now(timezone.utc),
        )
    ]
    session = _Session(rows)

    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM", 5)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_MIN_OCCURRENCES_FOR_RETIRE", 8)

    changed = await archivist_pipeline._apply_pattern_lifecycle(session)
    assert changed == 0
    assert rows[0].status == "candidate"
    assert rows[0].active is True


def test_regime_thresholds_shift_for_risk_off(monkeypatch) -> None:
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_PROMOTION_THRESHOLD_PCT", 65.0)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_RETIRE_THRESHOLD_PCT", 45.0)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM", 5)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_MIN_OCCURRENCES_FOR_RETIRE", 8)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_REGIME_ADJUSTMENTS_ENABLED", True)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_REGIME_RISK_OFF_PROMOTION_DELTA_PCT", 5.0)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_REGIME_RISK_OFF_RETIRE_DELTA_PCT", 3.0)

    thresholds = archivist_pipeline._lifecycle_thresholds_for_regime("risk_off_high_dispersion")
    assert thresholds["promotion_threshold_pct"] == 70.0
    assert thresholds["retire_threshold_pct"] == 48.0
    assert thresholds["min_occurrences_for_confirm"] == 6
    assert thresholds["min_occurrences_for_retire"] == 8
