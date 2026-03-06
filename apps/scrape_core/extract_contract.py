from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ExtractedItem:
    source_id: str
    url: str
    canonical_url: str
    headline: str | None = None
    published_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractionResult:
    source_id: str
    items: list[ExtractedItem]
    confidence: str = "high"  # high|medium|low
    reason: str | None = None
    parser_version: str | None = None
