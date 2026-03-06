from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SourceConfig:
    source_id: str
    type: str
    base_url: str
    enabled_by_default: bool
    parser: str
    timeout_secs: int
    retries: int
    backoff_base: float
    rate_limit_rps: float
    ticker_strategy: str
    tier: str = "secondary"
    required_for_success: bool = False
    cache_ttl_seconds: int = 0
    use_conditional_get: bool = False
    max_items_per_run: int = 500
    requires_auth: bool = False
    auth_env_key: str | None = None
    scope: str = "kenya_core"
    market_region: str = "kenya"
    signal_class: str = "issuer_disclosure"
    theme: str | None = None
    primary_use: str | None = None
    disabled_reason: str | None = None
    kenya_impact_enabled: bool = False
    kenya_impact_weight: float = 1.0
    premium: bool = False


@dataclass(slots=True)
class RawAnnouncement:
    source_id: str
    headline: str
    url: str
    published_at: datetime | str | None = None
    ticker_hint: str | None = None
    company_hint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedAnnouncement:
    announcement_id: str
    source_id: str
    ticker: str | None
    company: str | None
    headline: str
    url: str
    canonical_url: str
    announcement_date: datetime | None
    announcement_type: str
    type_confidence: float
    details: str | None
    content_hash: str | None
    raw_payload: dict[str, Any] | None
    classifier_version: str | None = None
    normalizer_version: str | None = None


@dataclass(slots=True)
class SourceRunStats:
    items_found: int = 0
    inserted: int = 0
    duplicates: int = 0
    duration_ms: int = 0
    error_type: str | None = None
    error: str | None = None
