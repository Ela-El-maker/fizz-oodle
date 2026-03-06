from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Awaitable, Callable


@dataclass(slots=True)
class SentimentSourceConfig:
    source_id: str
    type: str
    base_url: str
    enabled_by_default: bool
    parser: str
    timeout_secs: int
    retries: int
    backoff_base: float
    rate_limit_rps: float
    weight: float
    requires_auth: bool
    tier: str = "secondary"
    required_for_success: bool = False
    cache_ttl_seconds: int = 0
    use_conditional_get: bool = False
    max_items_per_run: int = 500
    auth_env_key: str | None = None
    scope: str = "kenya_extended"
    market_region: str = "kenya"
    signal_class: str = "news_signal"
    theme: str | None = None
    primary_use: str | None = None
    disabled_reason: str | None = None
    kenya_impact_enabled: bool = False
    kenya_impact_weight: float = 1.0
    premium: bool = False


@dataclass(slots=True)
class RawPost:
    source_id: str
    url: str | None
    canonical_url: str | None
    author: str | None
    title: str | None
    content: str
    published_at: datetime | None
    fetched_at: datetime
    raw_payload: dict | None


@dataclass(slots=True)
class MentionScore:
    ticker: str
    company_name: str | None
    sentiment_score: float
    sentiment_label: str
    confidence: float
    source_weight: float
    reasons: dict
    model_version: str
    llm_used: bool
    scored_at: datetime


@dataclass(slots=True)
class WeeklyRow:
    week_start: date
    ticker: str
    company_name: str
    mentions_count: int
    bullish_count: int
    bearish_count: int
    neutral_count: int
    bullish_pct: float
    bearish_pct: float
    neutral_pct: float
    weighted_score: float
    confidence: float
    top_sources: dict
    notable_quotes: list
    wow_delta: float | None
    generated_at: datetime


CollectorFn = Callable[[SentimentSourceConfig, datetime, datetime], Awaitable[list[RawPost]]]
