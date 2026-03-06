from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}
MODEL_VERSION = "sentiment_rules_v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonicalize_url(url: str | None, base_url: str | None = None) -> str | None:
    if not url:
        return None
    resolved = urljoin(base_url or "", url)
    parts = urlsplit(resolved)
    filtered = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low in TRACKING_QUERY_KEYS:
            continue
        if any(low.startswith(p) for p in TRACKING_QUERY_PREFIXES):
            continue
        filtered.append((key, value))
    query = urlencode(filtered, doseq=True)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def make_post_id(
    source_id: str,
    canonical_url: str | None,
    title: str | None,
    content: str,
    published_at: datetime | None,
) -> str:
    normalized_title = normalize_text(title).lower()
    normalized_content = normalize_text(content).lower()
    date_part = published_at.date().isoformat() if published_at else ""
    payload = "|".join([source_id, canonical_url or "", normalized_title, normalized_content[:512], date_part])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def payload_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

