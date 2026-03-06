from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.sentiment.normalize import normalize_text
from apps.agents.sentiment.score_rules import score_text
from apps.core.models import SentimentRawPost

THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "oil": ("oil", "brent", "crude", "opec", "fuel", "shipping", "freight", "port"),
    "commodities": ("commodity", "commodities", "metals", "agriculture", "fertilizer"),
    "usd_strength": ("usd", "u.s. dollar", "dollar index", "federal reserve", "fed", "forex", "fx"),
    "bonds_yields": ("bond", "bonds", "yield", "yields", "treasury", "sovereign debt", "coupon"),
    "earnings_cycle": ("earnings", "guidance", "profit warning", "quarterly results", "eps"),
    "dividends_flow": ("dividend", "payout", "book closure", "yield"),
    "global_equities_trading": ("stocks", "equities", "trading", "index", "risk off", "risk-on", "selloff", "rally"),
    "global_macro": ("inflation", "rates", "gdp", "macro", "liquidity", "central bank"),
    "ai_research": ("ai research", "model benchmark", "training", "inference", "compute"),
    "ai_platforms": ("openai", "deepmind", "anthropic", "ai", "llm", "model", "gpu", "inference"),
    "global_tech_risk": ("openai", "deepmind", "anthropic", "ai", "llm", "gpu", "cloud", "platform"),
    "kenya_business_news": ("kenya", "nairobi", "nse", "cbk", "cma", "earnings", "dividend", "banking"),
    "global_risk": ("risk-off", "risk on", "volatility", "global equities", "bond yields"),
}

THEME_GROUPS: dict[str, str] = {
    "oil": "commodities",
    "commodities": "commodities",
    "usd_strength": "macro_rates",
    "bonds_yields": "macro_rates",
    "global_macro": "macro_rates",
    "global_risk": "macro_rates",
    "earnings_cycle": "equities_fundamentals",
    "dividends_flow": "equities_fundamentals",
    "global_equities_trading": "equities_fundamentals",
    "ai_platforms": "ai_tech",
    "ai_research": "ai_tech",
    "global_tech_risk": "ai_tech",
    "kenya_business_news": "kenya_business",
}


@dataclass(slots=True)
class ThemeAggregate:
    mentions: int = 0
    bullish: int = 0
    bearish: int = 0
    neutral: int = 0
    score_sum: float = 0.0
    confidence_sum: float = 0.0
    kenya_rel_sum: float = 0.0
    sources: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.sources is None:
            self.sources = {}


def infer_themes(text: str, source_theme: str | None = None) -> list[str]:
    if source_theme:
        return [source_theme.strip().lower()]
    low = text.lower()
    themes = [theme for theme, terms in THEME_KEYWORDS.items() if any(term in low for term in terms)]
    return themes


def infer_kenya_relevance(
    *,
    theme: str,
    text: str,
    scope: str,
    source_weight: float,
) -> float:
    if scope != "global_outside":
        return 1.0
    relevance = 0.35
    low = text.lower()
    if any(token in low for token in ("kenya", "nairobi", "east africa", "mombasa", "nse", "cbk", "cma")):
        relevance += 0.35
    if theme in {"oil", "commodities", "usd_strength", "bonds_yields", "global_macro", "global_risk"}:
        relevance += 0.2
    elif theme in {"earnings_cycle", "dividends_flow", "global_equities_trading"}:
        relevance += 0.15
    elif theme in {"ai_platforms", "ai_research", "global_tech_risk"}:
        relevance += 0.1
    relevance += min(0.15, max(0.0, (source_weight - 1.0) * 0.15))
    return max(0.0, min(1.0, relevance))


async def _load_posts_for_range(session: AsyncSession, start_utc: datetime, end_utc: datetime) -> list[SentimentRawPost]:
    rows = (
        await session.execute(
            select(SentimentRawPost).where(
                or_(
                    and_(
                        SentimentRawPost.published_at.is_not(None),
                        SentimentRawPost.published_at >= start_utc,
                        SentimentRawPost.published_at <= end_utc,
                    ),
                    and_(
                        SentimentRawPost.published_at.is_(None),
                        SentimentRawPost.fetched_at >= start_utc,
                        SentimentRawPost.fetched_at <= end_utc,
                    ),
                )
            )
        )
    ).scalars().all()
    return rows


def _aggregate_posts(
    posts: list[SentimentRawPost],
    *,
    source_weights: dict[str, float],
) -> dict[str, ThemeAggregate]:
    out: dict[str, ThemeAggregate] = defaultdict(ThemeAggregate)
    for post in posts:
        payload = post.raw_payload if isinstance(post.raw_payload, dict) else {}
        base_text = normalize_text(f"{post.title or ''} {post.content or ''}")
        if not base_text:
            continue
        source_theme = payload.get("theme")
        payload_themes = payload.get("themes")
        themes: list[str]
        if isinstance(payload_themes, list) and payload_themes:
            themes = [str(t).strip().lower() for t in payload_themes if str(t).strip()]
        else:
            themes = infer_themes(base_text, source_theme=str(source_theme) if source_theme else None)
        if not themes:
            continue

        scored = score_text(base_text)
        source_weight = float(source_weights.get(post.source_id, 1.0))
        scope = str(payload.get("scope") or "kenya_extended")
        explicit_relevance = payload.get("kenya_relevance")
        for theme in themes:
            agg = out[theme]
            agg.mentions += 1
            if scored.label == "bullish":
                agg.bullish += 1
            elif scored.label == "bearish":
                agg.bearish += 1
            else:
                agg.neutral += 1
            agg.score_sum += float(scored.score) * source_weight
            agg.confidence_sum += float(scored.confidence)
            if explicit_relevance is None:
                kenya_rel = infer_kenya_relevance(
                    theme=theme,
                    text=base_text,
                    scope=scope,
                    source_weight=source_weight,
                )
            else:
                try:
                    kenya_rel = float(explicit_relevance)
                except Exception:
                    kenya_rel = infer_kenya_relevance(
                        theme=theme,
                        text=base_text,
                        scope=scope,
                        source_weight=source_weight,
                    )
            agg.kenya_rel_sum += max(0.0, min(1.0, kenya_rel))
            agg.sources[post.source_id] = int(agg.sources.get(post.source_id) or 0) + 1

    return out


def _rows_from_aggregate(
    aggregate: dict[str, ThemeAggregate],
    *,
    prev_scores: dict[str, float] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    prev_scores = prev_scores or {}
    for theme, agg in aggregate.items():
        if agg.mentions <= 0:
            continue
        mentions = float(agg.mentions)
        weighted_score = agg.score_sum / mentions
        bullish_pct = (agg.bullish / mentions) * 100.0
        bearish_pct = (agg.bearish / mentions) * 100.0
        neutral_pct = (agg.neutral / mentions) * 100.0
        wow_delta = None
        if theme in prev_scores:
            wow_delta = weighted_score - float(prev_scores[theme])
        rows.append(
            {
                "theme": theme,
                "theme_group": THEME_GROUPS.get(theme, "other"),
                "mentions": int(agg.mentions),
                "bullish_pct": round(bullish_pct, 2),
                "bearish_pct": round(bearish_pct, 2),
                "neutral_pct": round(neutral_pct, 2),
                "weighted_score": round(weighted_score, 4),
                "confidence": round(agg.confidence_sum / mentions, 3),
                "kenya_relevance_avg": round(agg.kenya_rel_sum / mentions, 3),
                "wow_delta": round(wow_delta, 4) if wow_delta is not None else None,
                "top_sources": dict(sorted((agg.sources or {}).items(), key=lambda item: item[1], reverse=True)[:3]),
            }
        )
    rows.sort(key=lambda row: (int(row["mentions"]), float(row["kenya_relevance_avg"])), reverse=True)
    return rows


def _week_window_utc(week_start: date, *, window_days: int = 7) -> tuple[datetime, datetime]:
    eat = ZoneInfo("Africa/Nairobi")
    start_eat = datetime.combine(week_start, time.min, tzinfo=eat)
    end_eat = start_eat + timedelta(days=max(1, int(window_days)))
    return start_eat.astimezone(timezone.utc), end_eat.astimezone(timezone.utc)


async def build_theme_summary_for_week(
    session: AsyncSession,
    *,
    week_start: date,
    source_weights: dict[str, float] | None = None,
    window_days: int = 7,
) -> list[dict]:
    source_weights = source_weights or {}
    start_utc, end_utc = _week_window_utc(week_start, window_days=window_days)
    prev_start_utc, prev_end_utc = _week_window_utc(week_start - timedelta(days=7), window_days=window_days)

    current_posts = await _load_posts_for_range(session, start_utc, end_utc)
    prev_posts = await _load_posts_for_range(session, prev_start_utc, prev_end_utc)
    current_agg = _aggregate_posts(current_posts, source_weights=source_weights)
    prev_agg = _aggregate_posts(prev_posts, source_weights=source_weights)
    prev_scores = {
        theme: (agg.score_sum / float(agg.mentions))
        for theme, agg in prev_agg.items()
        if agg.mentions > 0
    }
    return _rows_from_aggregate(current_agg, prev_scores=prev_scores)
