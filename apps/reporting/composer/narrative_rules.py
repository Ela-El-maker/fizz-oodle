from __future__ import annotations

from typing import Any


def _clip(text: str, limit: int) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def style_lint(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary or {})
    out["headline"] = _clip(str(out.get("headline") or ""), 180)
    out["plain_summary"] = _clip(str(out.get("plain_summary") or ""), 420)

    for key, item_limit, line_limit in (
        ("key_drivers", 6, 180),
        ("risks", 6, 180),
        ("sector_highlights", 6, 180),
        ("next_watch", 6, 180),
    ):
        rows = out.get(key) or []
        if not isinstance(rows, list):
            rows = [str(rows)]
        out[key] = [_clip(str(v), line_limit) for v in rows if str(v).strip()][:item_limit]
    return out


def inject_uncertainty(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary or {})
    quality = out.get("quality") if isinstance(out.get("quality"), dict) else {}
    flags = quality.get("degradation_flags") if isinstance(quality, dict) else []
    if not isinstance(flags, list):
        flags = []
    if not flags:
        return out
    text = str(out.get("plain_summary") or "")
    if "confidence is reduced" in text.lower():
        return out
    warning = " Confidence is reduced due to data degradation in this cycle."
    out["plain_summary"] = (text + warning).strip()
    return out
