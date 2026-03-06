from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class MarketMover:
    ticker: str
    close: float | None
    pct_change: float | None


@dataclass(slots=True)
class InputsBundle:
    report_type: str
    period_key: date
    market_date: date | None
    briefing: dict | None
    announcements: list[dict]
    sentiment_rows: list[dict]
    index_rows: list[dict]
    fx_rows: list[dict]
    movers: list[MarketMover]
    losers: list[MarketMover]
    price_history: dict[str, list[dict]] = field(default_factory=dict)
    global_theme_summary: list[dict] = field(default_factory=list)
    archivist_feedback: dict | None = None
    calibration_feedback: dict | None = None
    degraded_reasons: list[str] = field(default_factory=list)
    inputs_summary: dict = field(default_factory=dict)
    upstream_quality: dict = field(default_factory=dict)


@dataclass(slots=True)
class AnalystPayload:
    report_type: str
    period_key: str
    title: str
    overview: list[str]
    market_snapshot: dict
    key_events: list[dict]
    sentiment_pulse: list[dict]
    archivist_feedback: dict | None
    signal_intelligence: dict
    global_context: dict
    what_to_watch: list[str]
    data_quality: list[str]
    degraded: bool
