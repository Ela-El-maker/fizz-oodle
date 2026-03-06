from __future__ import annotations

from typing import Iterable

from apps.reporting.composer.contracts import EvidenceRef


def dedupe_evidence(rows: Iterable[EvidenceRef], *, limit: int = 20) -> list[EvidenceRef]:
    out: list[EvidenceRef] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        item = dict(row or {})
        key = (
            str(item.get("type") or ""),
            str(item.get("source_id") or ""),
            str(item.get("url_or_id") or ""),
            str(item.get("timestamp") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)  # type: ignore[arg-type]
        if len(out) >= max(1, limit):
            break
    return out


def from_events(
    events: Iterable[dict],
    *,
    type_name: str,
    source_key: str = "source_id",
    time_key: str = "timestamp",
    link_key: str = "url",
    id_key: str = "id",
    confidence_key: str = "confidence",
    limit: int = 20,
) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        url_or_id = str(event.get(link_key) or event.get(id_key) or "").strip()
        if not url_or_id:
            continue
        refs.append(
            {
                "type": type_name,
                "source_id": str(event.get(source_key) or "unknown"),
                "timestamp": str(event.get(time_key) or "") or None,
                "url_or_id": url_or_id,
                "confidence": float(event.get(confidence_key)) if event.get(confidence_key) is not None else None,
            }
        )
    return dedupe_evidence(refs, limit=limit)
