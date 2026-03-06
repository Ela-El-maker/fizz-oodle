from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(slots=True)
class PricePoint:
    date: date
    ticker: str
    close: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: float | None
    currency: str
    source_id: str
    fetched_at: datetime
    raw_payload: dict | None


@dataclass(slots=True)
class PriceSnapshotNormalized:
    date: date
    ticker: str
    exchange: str
    close: float | None
    prev_close: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: float | None
    pct_change: float | None
    direction: Literal["up", "down", "flat", "unknown"]
    source_id: str
    source_priority: int
    source_confidence: float
    status: Literal["ok", "degraded", "missing"]
    error_type: str | None
    error: str | None
    fetched_at: datetime
    raw_payload: dict | None


@dataclass(slots=True)
class IndexPoint:
    date: date
    index_name: str
    value: float | None
    change_val: float | None
    pct_change: float | None
    source_id: str
    fetched_at: datetime
    raw_payload: dict | None


@dataclass(slots=True)
class FxPoint:
    date: date
    pair: str
    rate: float
    source_id: str
    fetched_at: datetime
    raw_payload: dict | None


@dataclass(slots=True)
class HeadlinePoint:
    date: date
    source_id: str
    headline: str
    url: str
    published_at: datetime | None
    fetched_at: datetime
    matched_tickers: list[str] | None = None
    content_hash: str | None = None
    trust_rank: int = 3
    relevance_score: float = 0.5
    confidence: float = 0.5
    raw_payload: dict | None = None


@dataclass(slots=True)
class ForexSnapshot:
    date: date
    pair: str
    rate: float | None
    source_id: str
    status: Literal["fresh", "stale_fallback", "missing"]
    age_hours: float | None
    confidence: float
    fetched_at: datetime
    raw_payload: dict | None = None


@dataclass(slots=True)
class MarketBrief:
    market_pulse: str
    drivers: list[str]
    unusual_signals: list[str]
    narrative_interpretation: str
    confidence_level: Literal["high", "medium", "low"]
    confidence_score: float
    confidence_reason: str
    model: str
    provider: str
    llm_used: bool
    llm_error: str | None = None
