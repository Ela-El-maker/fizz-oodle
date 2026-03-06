from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from dateutil import parser as date_parser

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref"}
NORMALIZER_VERSION = "stage2-v1"


def normalize_headline(text: str) -> str:
    if not text:
        return ""
    compact = " ".join(text.replace("\u2013", "-").replace("\u2014", "-").split())
    return compact.strip()


def canonicalize_url(url: str, base_url: str | None = None) -> str:
    resolved = urljoin(base_url or "", url)
    parts = urlsplit(resolved)
    filtered_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS:
            continue
        if any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        filtered_query.append((key, value))

    query = urlencode(filtered_query, doseq=True)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def parse_datetime_to_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = date_parser.parse(value)
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
