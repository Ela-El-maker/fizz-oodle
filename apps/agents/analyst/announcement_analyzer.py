from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from dateutil import parser as date_parser


_POSITIVE_TYPES = {"dividend", "rights_issue"}
_NEGATIVE_TYPES = {"profit_warning", "trading_suspension"}
_AMBIGUOUS_TYPES = {"board_change", "agm_egm", "merger_acquisition", "other", "regulatory_filing", "earnings"}

_POSITIVE_HINTS = (
    "profit up",
    "record",
    "approval",
    "approved",
    "dividend",
    "interim results",
    "beats",
    "growth",
)
_NEGATIVE_HINTS = (
    "profit warning",
    "loss",
    "suspension",
    "below expectations",
    "shortfall",
    "downgrade",
    "decline",
)


@dataclass(slots=True)
class AnnouncementSignal:
    ticker: str
    announcement_signal: str  # positive|negative|neutral|none
    weighted_positive: float
    weighted_negative: float
    weighted_neutral: float
    high_severity_recent: bool
    latest_announcement_type: str | None
    recent_count: int


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = date_parser.parse(str(value))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _classify_direction(announcement_type: str, headline: str) -> str:
    t = (announcement_type or "other").strip().lower()
    h = (headline or "").lower()

    if t in _POSITIVE_TYPES:
        return "positive"
    if t in _NEGATIVE_TYPES:
        return "negative"

    if t in _AMBIGUOUS_TYPES:
        pos_hits = sum(1 for token in _POSITIVE_HINTS if token in h)
        neg_hits = sum(1 for token in _NEGATIVE_HINTS if token in h)
        if pos_hits > neg_hits:
            return "positive"
        if neg_hits > pos_hits:
            return "negative"
        return "neutral"

    return "neutral"


def analyze_announcement_signal(
    *,
    ticker: str,
    rows: list[dict],
    now_utc: datetime,
) -> AnnouncementSignal:
    relevant = [r for r in rows if str(r.get("ticker") or "").upper() == ticker.upper()]
    if not relevant:
        return AnnouncementSignal(
            ticker=ticker,
            announcement_signal="none",
            weighted_positive=0.0,
            weighted_negative=0.0,
            weighted_neutral=0.0,
            high_severity_recent=False,
            latest_announcement_type=None,
            recent_count=0,
        )

    weighted_positive = 0.0
    weighted_negative = 0.0
    weighted_neutral = 0.0
    high_severity_recent = False

    def _row_sort_key(r: dict) -> str:
        return str(r.get("first_seen_at") or r.get("date") or "")

    ordered = sorted(relevant, key=_row_sort_key, reverse=True)
    latest_type = str(ordered[0].get("type") or ordered[0].get("announcement_type") or "") or None

    for row in relevant:
        ann_type = str(row.get("type") or row.get("announcement_type") or "other")
        headline = str(row.get("headline") or "")
        sev = str(row.get("severity") or "").lower().strip()
        first_seen = _parse_dt(row.get("first_seen_at") or row.get("date"))
        hours_since = (now_utc - first_seen).total_seconds() / 3600.0 if first_seen else 9999.0
        weight = 2.0 if hours_since < 48.0 else 1.0

        direction = _classify_direction(ann_type, headline)
        if direction == "positive":
            weighted_positive += weight
        elif direction == "negative":
            weighted_negative += weight
        else:
            weighted_neutral += weight

        if sev == "high" and hours_since <= 24.0:
            high_severity_recent = True

    if weighted_positive == weighted_negative == weighted_neutral == 0.0:
        final = "none"
    elif weighted_positive > weighted_negative and weighted_positive >= weighted_neutral:
        final = "positive"
    elif weighted_negative > weighted_positive and weighted_negative >= weighted_neutral:
        final = "negative"
    else:
        final = "neutral"

    return AnnouncementSignal(
        ticker=ticker,
        announcement_signal=final,
        weighted_positive=round(weighted_positive, 3),
        weighted_negative=round(weighted_negative, 3),
        weighted_neutral=round(weighted_neutral, 3),
        high_severity_recent=high_severity_recent,
        latest_announcement_type=latest_type,
        recent_count=len(relevant),
    )
