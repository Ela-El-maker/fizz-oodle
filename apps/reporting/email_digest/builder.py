from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.config import get_settings
from apps.core.models import Announcement, InsightCard, SentimentDigestReport
from apps.reporting.email_digest.contracts import (
    DigestExplainer,
    DigestKpi,
    DigestLink,
    DigestOneMinute,
    DigestStory,
    ExecutiveDigestPayload,
)

settings = get_settings()
EAT = ZoneInfo("Africa/Nairobi")

GLOSSARY: dict[str, str] = {
    "yield": "Yield is the annual return investors receive from a bond or dividend, expressed as a percentage.",
    "risk-off": "Risk-off means investors are moving away from risky assets into safer assets like cash or government bonds.",
    "guidance": "Guidance is management's forward-looking estimate of expected company performance.",
    "sovereign": "Sovereign refers to government-issued debt, usually treasury bills or bonds.",
    "liquidity": "Liquidity is how easily assets or cash are available without sharply moving prices.",
    "fed": "Fed refers to the U.S. Federal Reserve, whose rates can affect global capital flows and local currencies.",
    "brent": "Brent is a global oil benchmark; when it rises, fuel and transport costs often rise too.",
}

CORE_ALERT_TYPES = {
    "earnings",
    "dividend",
    "board_change",
    "regulator",
    "guidance",
    "rights_issue",
    "merger_acquisition",
    "profit_warning",
    "suspension",
    "agm_egm",
}


def _trim(text: str | None, limit: int = 260) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def _parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _to_eat_label(value: datetime | None) -> str:
    if value is None:
        return ""
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(EAT)
    return dt.strftime("%Y-%m-%d %I:%M %p EAT")


def _confidence_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _normalize_type(value: str | None) -> str:
    raw = (value or "other").strip().lower().replace(" ", "_")
    return raw or "other"


def _lane_label(scope: str) -> str:
    if scope == "global_outside":
        return "Global Outside"
    if scope == "kenya_extended":
        return "Kenya Extended"
    return "Kenya Core"


def _build_announcement_story(row: Announcement, next_watch: list[str]) -> DigestStory:
    raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
    scope = str(raw.get("scope") or "kenya_core")
    impact_score = int(raw.get("kenya_impact_score") or (100 if scope != "global_outside" else 0))
    channels = raw.get("transmission_channels") if isinstance(raw.get("transmission_channels"), list) else []
    sectors = raw.get("affected_sectors") if isinstance(raw.get("affected_sectors"), list) else []
    theme = str(raw.get("theme") or row.announcement_type or "").strip() or None
    conf = _confidence_level(_parse_float(row.type_confidence, 0.5))

    if scope == "global_outside":
        why = (
            f"Global signal transmitted via {', '.join(channels[:3])}."
            if channels
            else "Global development with potential pass-through effects into Kenya assets and sectors."
        )
    else:
        why = "Local disclosure that can shift valuation expectations, governance confidence, and near-term positioning."

    who = []
    if row.ticker:
        who.append(row.ticker)
    who.extend([str(s) for s in sectors[:3] if str(s).strip()])
    who_text = ", ".join(who) if who else "Kenyan listed peers in the same sector"

    watch = next_watch[0] if next_watch else "Next official update, management guidance, and immediate price/volume reaction."

    source_meta = f"{row.source_id}"
    if row.first_seen_at:
        source_meta = f"{source_meta} · {_to_eat_label(row.first_seen_at)}"

    return {
        "lane": _lane_label(scope),
        "title": _trim(row.headline, 180),
        "theme": theme,
        "impact_score": impact_score,
        "confidence": conf,
        "what_happened": _trim(row.details or row.headline, 260),
        "why_matters": _trim(why, 220),
        "who_affected": _trim(who_text, 140),
        "watch_next": _trim(watch, 180),
        "sources": [
            {
                "label": "Read source",
                "url": row.url,
                "meta": source_meta,
            }
        ],
    }


def _dedupe_links(rows: list[DigestLink], *, limit: int) -> list[DigestLink]:
    out: list[DigestLink] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("url") or row.get("label") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _collect_explainers(*, texts: list[str], enabled: bool) -> list[DigestExplainer]:
    if not enabled:
        return []
    blob = " ".join(texts).lower()
    explainers: list[DigestExplainer] = []
    for term, meaning in GLOSSARY.items():
        if term in blob:
            explainers.append({"term": term.title(), "meaning": meaning})
    return explainers[:4]


async def build_executive_digest_payload(
    session: AsyncSession,
    *,
    target_date: date,
    a_context: dict[str, Any],
    max_stories: int,
    use_agent_f: bool,
    include_glossary: bool,
) -> ExecutiveDigestPayload:
    threshold = int(settings.EMAIL_ALERTS_KENYA_IMPACT_THRESHOLD)
    max_rows = max(24, max_stories * 8)
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=72)

    stmt = select(Announcement).order_by(desc(Announcement.first_seen_at)).limit(max_rows)
    announcements = (await session.execute(stmt)).scalars().all()
    fresh = [row for row in announcements if row.first_seen_at and row.first_seen_at >= cutoff]
    working_rows = fresh if fresh else announcements

    inside_rows: list[Announcement] = []
    outside_rows: list[Announcement] = []
    for row in working_rows:
        raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        scope = str(raw.get("scope") or "kenya_core")
        impact = int(raw.get("kenya_impact_score") or (100 if scope != "global_outside" else 0))
        promoted = bool(raw.get("promoted_to_core_feed", scope != "global_outside"))
        ann_type = _normalize_type(row.announcement_type)
        if scope == "global_outside":
            if impact >= threshold:
                outside_rows.append(row)
            continue
        if promoted and ann_type in CORE_ALERT_TYPES:
            inside_rows.append(row)

    def _score_row(row: Announcement) -> tuple[float, datetime]:
        raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        impact = _parse_float(raw.get("kenya_impact_score"), 100.0)
        conf = _parse_float(row.type_confidence, 0.5)
        bonus = 10.0 if bool(row.alerted) else 0.0
        seen = row.first_seen_at or datetime.min.replace(tzinfo=timezone.utc)
        return (impact + (conf * 20.0) + bonus, seen)

    inside_rows = sorted(inside_rows, key=_score_row, reverse=True)[: max_stories]
    outside_rows = sorted(outside_rows, key=_score_row, reverse=True)[: max_stories]

    next_watch = a_context.get("next_watch") if isinstance(a_context.get("next_watch"), list) else []
    inside_cards = [_build_announcement_story(row, next_watch=next_watch) for row in inside_rows]
    outside_cards = [_build_announcement_story(row, next_watch=next_watch) for row in outside_rows]

    theme_items: list[dict[str, Any]] = []
    digest_row = (
        await session.execute(select(SentimentDigestReport).order_by(desc(SentimentDigestReport.week_start)).limit(1))
    ).scalars().first()
    if digest_row is not None and isinstance(digest_row.metrics, dict):
        summary = digest_row.metrics.get("theme_summary")
        if isinstance(summary, dict) and isinstance(summary.get("items"), list):
            theme_items = [row for row in summary.get("items", []) if isinstance(row, dict)]

    story_row = None
    if use_agent_f:
        story_row = (
            await session.execute(
                select(InsightCard)
                .where(InsightCard.scope_type == "market")
                .order_by(desc(InsightCard.generated_at))
                .limit(1)
            )
        ).scalars().first()

    story_sections = story_row.sections_json if story_row and isinstance(story_row.sections_json, dict) else {}
    story_quality = story_row.quality_json if story_row and isinstance(story_row.quality_json, dict) else {}
    story_conf = _confidence_level(_parse_float(story_quality.get("confidence_score"), 0.5))

    one_minute: DigestOneMinute = {
        "headline": _trim(str(a_context.get("headline") or "Kenya market intelligence update"), 180),
        "summary": _trim(str(a_context.get("summary") or "No concise summary available for this cycle."), 420),
        "confidence": _confidence_level(_parse_float(a_context.get("confidence_score"), 0.6)),
        "sources": _dedupe_links(
            [
                {
                    "label": _trim(str(item.get("headline") or "Source"), 90),
                    "url": str(item.get("url") or ""),
                    "meta": "Agent A headline",
                }
                for item in (a_context.get("headlines") or [])
                if isinstance(item, dict)
            ],
            limit=6,
        ),
    }

    global_to_kenya: list[str] = []
    if isinstance(story_sections.get("paragraphs"), list):
        global_to_kenya = [
            _trim(str(p), 320)
            for p in story_sections.get("paragraphs", [])
            if str(p).strip()
        ][:3]

    if not global_to_kenya:
        if outside_cards:
            global_to_kenya = [
                "Global pressure points are now visible in the high-impact lane; watch fuel, FX, and risk sentiment transmission into Kenya equities.",
                "Use outside-driver cards to prioritize exposure reviews before the next local session open.",
            ]
        else:
            global_to_kenya = [
                "No high-impact global signal crossed the Kenya threshold in this cycle.",
            ]

    global_driver_links = _dedupe_links(
        [
            {
                "label": _trim(str(ref.get("url_or_id") or ref.get("source_id") or "Narrator evidence"), 90),
                "url": str(ref.get("url_or_id") or ""),
                "meta": str(ref.get("source_id") or "Agent F"),
            }
            for ref in (story_sections.get("evidence_refs") or [])
            if isinstance(ref, dict)
        ],
        limit=6,
    )

    movers = a_context.get("top_movers") if isinstance(a_context.get("top_movers"), list) else []
    watchlist: list[str] = []
    for item in movers[:4]:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper().strip()
        pct = _parse_float(item.get("pct_change"), 0.0)
        if ticker:
            watchlist.append(f"{ticker}: move {pct:+.2f}% — confirm whether follow-through aligns with current narrative drivers.")

    for theme in theme_items[:3]:
        theme_name = str(theme.get("theme") or "theme").replace("_", " ").title()
        mentions = int(theme.get("mentions") or 0)
        score = _parse_float(theme.get("weighted_score"), 0.0)
        watchlist.append(f"{theme_name}: mentions {mentions}, score {score:+.3f} — track acceleration or reversal into next cycle.")

    for item in next_watch[:3]:
        if str(item).strip():
            watchlist.append(_trim(str(item), 180))

    watchlist = watchlist[:10]

    read_more = _dedupe_links(
        one_minute["sources"]
        + [link for card in inside_cards for link in (card.get("sources") or [])]
        + [link for card in outside_cards for link in (card.get("sources") or [])]
        + global_driver_links,
        limit=max(10, max_stories * 2),
    )

    explainer_texts = [
        one_minute["headline"],
        one_minute["summary"],
        " ".join(global_to_kenya),
        " ".join([str(card.get("title") or "") for card in outside_cards]),
    ]
    explainers = _collect_explainers(texts=explainer_texts, enabled=include_glossary)

    coverage_pct = _parse_float(a_context.get("coverage_pct"), 0.0)
    kpis: list[DigestKpi] = [
        {"label": "Kenya Core Signals", "value": str(len(inside_cards))},
        {"label": "Global Outside (High Impact)", "value": str(len(outside_cards))},
        {"label": "Impact Threshold", "value": f">= {threshold}"},
        {"label": "Price Coverage", "value": f"{coverage_pct:.1f}%"},
    ]

    data_quality: list[str] = [
        f"Announcement window: {len(working_rows)} records reviewed, {len(inside_cards) + len(outside_cards)} surfaced in digest.",
        f"Narrator synthesis: {'active' if story_row is not None else 'fallback'} ({story_conf} confidence framing).",
        f"Theme coverage: {len(theme_items)} sentiment themes available from latest sentiment digest.",
    ]

    llm_error = str(a_context.get("llm_error") or "").strip()
    if llm_error:
        data_quality.append("Agent A LLM brief degraded in this cycle; deterministic summary fallback applied.")

    return {
        "date_label": target_date.strftime("%Y-%m-%d"),
        "kpis": kpis,
        "one_minute": one_minute,
        "inside_kenya": inside_cards,
        "outside_kenya": outside_cards,
        "global_to_kenya": global_to_kenya,
        "global_driver_links": global_driver_links,
        "watchlist": watchlist,
        "read_more": read_more,
        "explainers": explainers,
        "data_quality": data_quality,
    }
