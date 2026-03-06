from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "yclid")


def normalize_canonical_url(url: str | None, *, base_url: str | None = None) -> str:
    if not url:
        return ""
    raw = url.strip()
    if base_url:
        raw = urljoin(base_url, raw)

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"

    clean_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k and not any(k.lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    ]
    clean_query.sort(key=lambda item: (item[0], item[1]))

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    return urlunparse((scheme, netloc, path, "", urlencode(clean_query), ""))


def canonical_url_fingerprint(url: str | None, *, base_url: str | None = None) -> str:
    canonical = normalize_canonical_url(url, base_url=base_url)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_fingerprint(*parts: str | None) -> str:
    payload = "|".join((part or "").strip() for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
