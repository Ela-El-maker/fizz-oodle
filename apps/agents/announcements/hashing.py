from __future__ import annotations

import hashlib


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_announcement_id(source_id: str, canonical_url: str, normalized_headline: str, yyyymmdd: str) -> str:
    payload = "|".join([source_id.strip().lower(), canonical_url.strip(), normalized_headline.strip().lower(), yyyymmdd])
    return _sha256(payload)


def make_content_hash(value: str) -> str:
    return _sha256(value.strip())
