from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import statistics

from apps.agents.analyst.announcement_analyzer import analyze_announcement_signal
from apps.agents.analyst.convergence_engine import compute_convergence
from apps.agents.analyst.price_analyzer import analyze_price_signal
from apps.agents.analyst.sentiment_analyzer import analyze_sentiment_signal
from apps.agents.analyst.types import InputsBundle
from apps.core.config import get_settings

settings = get_settings()


def _market_regime_from_momentum(price_signal_rows: list[dict]) -> str:
    momenta = [float(r.get("momentum_pct") or 0.0) for r in price_signal_rows if r.get("momentum_pct") is not None]
    if not momenta:
        return "unknown"

    avg_momentum = sum(momenta) / len(momenta)
    dispersion = statistics.pstdev(momenta) if len(momenta) > 1 else 0.0

    if avg_momentum > 1.5:
        base = "risk_on"
    elif avg_momentum < -1.5:
        base = "risk_off"
    else:
        base = "neutral"

    if dispersion > 3.0:
        return f"{base}_high_dispersion"
    return base


def _impact_success_rate(archivist_feedback: dict | None, announcement_type: str | None, direction: str) -> float | None:
    if not archivist_feedback or not announcement_type:
        return None
    impacts = archivist_feedback.get("impacts") or []
    ann_type = str(announcement_type).strip().lower()
    for row in impacts:
        if str(row.get("announcement_type") or "").strip().lower() != ann_type:
            continue
        if direction == "bullish":
            return float(row.get("positive_rate") or 0.0) / 100.0
        if direction == "bearish":
            return float(row.get("negative_rate") or 0.0) / 100.0
        return None
    return None


def _ticker_pattern_success_rate(archivist_feedback: dict | None, ticker: str) -> float | None:
    if not archivist_feedback:
        return None
    patterns = archivist_feedback.get("patterns") or []
    candidates = [
        float(p.get("accuracy_pct") or 0.0) / 100.0
        for p in patterns
        if str(p.get("ticker") or "").upper() == ticker.upper()
    ]
    if not candidates:
        return None
    return max(candidates)


def _active_confirmed_pattern_count(feedback_patterns: list[dict]) -> int:
    if not feedback_patterns:
        return 0
    with_status = [p for p in feedback_patterns if isinstance(p, dict) and "status" in p]
    if not with_status:
        return len(feedback_patterns)
    return sum(1 for p in with_status if str(p.get("status") or "").lower() == "confirmed")


def _cap_pattern_rate(pattern_rate: float, cap_factor: float) -> float:
    factor = max(0.0, min(1.0, float(cap_factor)))
    # Keep pattern influence centered on neutral (0.5), but damp extremes.
    return max(0.0, min(1.0, 0.5 + ((float(pattern_rate) - 0.5) * factor)))


def build_features(bundle: InputsBundle) -> dict:
    events_by_ticker: dict[str, list[dict]] = defaultdict(list)
    events_by_type: dict[str, int] = defaultdict(int)

    for event in bundle.announcements:
        ticker = event.get("ticker") or "UNKNOWN"
        events_by_ticker[ticker].append(event)
        events_by_type[event.get("type") or "other"] += 1

    event_groups = [
        {
            "ticker": ticker,
            "count": len(items),
            "types": sorted({(i.get("type") or "other") for i in items}),
            "latest": items[0],
        }
        for ticker, items in sorted(events_by_ticker.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]

    sentiment_sorted = sorted(
        bundle.sentiment_rows,
        key=lambda r: (
            abs(float(r.get("wow_delta") or 0.0)),
            abs(float(r.get("weighted_score") or 0.0)),
            float(r.get("confidence") or 0.0),
        ),
        reverse=True,
    )

    sentiment_highlights = sentiment_sorted[:8]

    movers = [
        {"ticker": m.ticker, "close": m.close, "pct_change": m.pct_change}
        for m in bundle.movers
    ]
    losers = [
        {"ticker": m.ticker, "close": m.close, "pct_change": m.pct_change}
        for m in bundle.losers
    ]

    sentiment_by_ticker = {
        str(r.get("ticker") or "").upper(): r
        for r in bundle.sentiment_rows
        if str(r.get("ticker") or "").strip()
    }

    now_utc = datetime.now(timezone.utc)
    all_tickers = sorted(
        {
            *[str(t).upper() for t in bundle.price_history.keys()],
            *[str(a.get("ticker") or "").upper() for a in bundle.announcements if a.get("ticker")],
            *[str(s.get("ticker") or "").upper() for s in bundle.sentiment_rows if s.get("ticker")],
            *[m.ticker.upper() for m in bundle.movers],
            *[m.ticker.upper() for m in bundle.losers],
        }
    )

    feedback_payload = bundle.archivist_feedback or {}
    feedback_patterns = feedback_payload.get("patterns") or []
    feedback_impacts = feedback_payload.get("impacts") or []
    feedback_available = bool(feedback_patterns or feedback_impacts)
    active_confirmed_patterns = _active_confirmed_pattern_count(feedback_patterns)
    pattern_weight_cap_factor = float(settings.ANALYST_PATTERN_FEEDBACK_WEIGHT_CAP)
    low_pattern_coverage = (
        feedback_available
        and active_confirmed_patterns < int(settings.ANALYST_PATTERN_FEEDBACK_MIN_ACTIVE_PATTERNS)
    )
    feedback_coverage_count = 0
    pattern_cap_applied_count = 0
    per_ticker_signals: list[dict] = []
    for ticker in all_tickers:
        if not ticker:
            continue

        price_signal = analyze_price_signal(
            ticker=ticker,
            history_rows=bundle.price_history.get(ticker, []),
        )
        ann_signal = analyze_announcement_signal(
            ticker=ticker,
            rows=bundle.announcements,
            now_utc=now_utc,
        )
        sent_signal = analyze_sentiment_signal(
            ticker=ticker,
            row=sentiment_by_ticker.get(ticker),
        )

        pattern_rate = _impact_success_rate(
            bundle.archivist_feedback,
            ann_signal.latest_announcement_type,
            direction="bullish" if sent_signal.sentiment_signal == "bullish" else "bearish",
        )
        if pattern_rate is None:
            pattern_rate = _ticker_pattern_success_rate(bundle.archivist_feedback, ticker)
        pattern_rate_raw = pattern_rate
        if pattern_rate_raw is not None:
            feedback_coverage_count += 1
        if pattern_rate_raw is not None and low_pattern_coverage:
            pattern_rate = _cap_pattern_rate(pattern_rate_raw, pattern_weight_cap_factor)
            pattern_cap_applied_count += 1

        convergence = compute_convergence(
            ticker=ticker,
            price=price_signal,
            announcement=ann_signal,
            sentiment=sent_signal,
            pattern_success_rate=pattern_rate,
        )
        confidence_pct = float(convergence.confidence_pct)
        decision_trace = dict(convergence.decision_trace or {})
        trace_steps = list(decision_trace.get("steps") or [])
        if pattern_rate_raw is not None and low_pattern_coverage:
            trace_steps.append(
                {
                    "step": "pattern_weight_cap",
                    "reason": "active_pattern_coverage_low",
                    "active_confirmed_patterns": active_confirmed_patterns,
                    "min_required_patterns": int(settings.ANALYST_PATTERN_FEEDBACK_MIN_ACTIVE_PATTERNS),
                    "cap_factor": round(pattern_weight_cap_factor, 3),
                    "raw_pattern_success_rate": round(pattern_rate_raw, 4),
                    "effective_pattern_success_rate": round(float(pattern_rate), 4),
                }
            )
        if settings.ANALYST_USE_ARCHIVIST_FEEDBACK and not feedback_available:
            confidence_pct = max(0.0, confidence_pct - 5.0)
            trace_steps.append(
                {
                    "step": "feedback_penalty",
                    "reason": "archivist_feedback_missing",
                    "confidence_delta": -5.0,
                }
            )
        decision_trace["steps"] = trace_steps
        decision_trace["final"] = {
            **(decision_trace.get("final") or {}),
            "confidence_pct": round(confidence_pct, 2),
        }

        per_ticker_signals.append(
            {
                "ticker": ticker,
                "price_signal": price_signal.price_signal,
                "momentum_pct": price_signal.momentum_pct,
                "volatility_pct": price_signal.volatility_pct,
                "volume_ratio": price_signal.volume_ratio,
                "announcement_signal": ann_signal.announcement_signal,
                "announcement_recent_count": ann_signal.recent_count,
                "announcement_latest_type": ann_signal.latest_announcement_type,
                "sentiment_signal": sent_signal.sentiment_signal,
                "sentiment_mentions": sent_signal.mention_count,
                "sentiment_wow_delta": sent_signal.wow_delta,
                "sentiment_momentum_state": sent_signal.momentum_state,
                "convergence_score": convergence.convergence_score,
                "convergence_direction": convergence.direction,
                "convergence_strength": convergence.strength,
                "confidence_pct": round(confidence_pct, 2),
                "anomalies": convergence.anomalies,
                "signals": convergence.signal_map,
                "pattern_success_rate": round(pattern_rate, 3) if pattern_rate is not None else None,
                "pattern_success_rate_raw": round(pattern_rate_raw, 3) if pattern_rate_raw is not None else None,
                "pattern_weight_capped": bool(pattern_rate_raw is not None and low_pattern_coverage),
                "decision_trace": decision_trace,
            }
        )

    per_ticker_signals.sort(
        key=lambda r: (
            int(r.get("convergence_score") or 0),
            float(r.get("confidence_pct") or 0.0),
            abs(float(r.get("momentum_pct") or 0.0)),
        ),
        reverse=True,
    )

    anomalies = [
        {
            "ticker": row["ticker"],
            "anomalies": row["anomalies"],
            "confidence_pct": row["confidence_pct"],
        }
        for row in per_ticker_signals
        if row.get("anomalies")
    ]

    signal_summary = {
        "market_regime": _market_regime_from_momentum(per_ticker_signals),
        "top_convergence": per_ticker_signals[:10],
        "anomalies": anomalies[:10],
        "decision_traces": [row["decision_trace"] for row in per_ticker_signals[:10] if row.get("decision_trace")],
        "feedback": {
            "applied": feedback_available,
            "coverage_pct": round((feedback_coverage_count / len(per_ticker_signals)) * 100.0, 2) if per_ticker_signals else 0.0,
            "patterns": len(feedback_patterns),
            "impacts": len(feedback_impacts),
            "active_confirmed_patterns": active_confirmed_patterns,
            "pattern_weight_capped": low_pattern_coverage,
            "pattern_weight_cap_factor": round(pattern_weight_cap_factor, 3) if low_pattern_coverage else None,
            "pattern_weight_cap_applied_count": pattern_cap_applied_count,
            "feedback_timestamp": (
                (feedback_payload.get("archive_latest_weekly") or {}).get("updated_at")
                if isinstance(feedback_payload.get("archive_latest_weekly"), dict)
                else None
            ),
        },
    }

    high_impact_global_events = [
        {
            "headline": str(row.get("headline") or "").strip(),
            "ticker": str(row.get("ticker") or "").upper().strip() or None,
            "theme": str(row.get("theme") or "global_macro").strip().lower(),
            "kenya_impact_score": int(row.get("kenya_impact_score") or 0),
            "source_id": row.get("source_id"),
            "transmission_channels": list(row.get("transmission_channels") or []),
            "affected_sectors": list(row.get("affected_sectors") or []),
            "url": row.get("url"),
        }
        for row in bundle.announcements
        if str(row.get("scope") or "").strip().lower() == "global_outside"
        and int(row.get("kenya_impact_score") or 0) >= int(settings.GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD)
    ]
    high_impact_global_events.sort(key=lambda row: int(row.get("kenya_impact_score") or 0), reverse=True)

    global_themes = sorted(
        [
            {
                "theme": str(row.get("theme") or "").strip().lower(),
                "theme_group": str(row.get("theme_group") or "other").strip().lower(),
                "count": int(row.get("count") or row.get("mentions") or 0),
                "weighted_score": float(row.get("weighted_score") or 0.0),
            }
            for row in (bundle.global_theme_summary or [])
            if isinstance(row, dict) and str(row.get("theme") or "").strip()
        ],
        key=lambda row: (int(row.get("count") or 0), abs(float(row.get("weighted_score") or 0.0))),
        reverse=True,
    )
    briefing_metrics = bundle.briefing.get("metrics") if isinstance(bundle.briefing, dict) else {}
    global_news_collected = int((briefing_metrics or {}).get("global_news_collected") or 0)
    theme_group_rollup: dict[str, dict[str, float]] = {}
    for row in global_themes:
        group = str(row.get("theme_group") or "other")
        current = theme_group_rollup.setdefault(group, {"mentions": 0.0, "score_weighted_sum": 0.0})
        mentions = float(row.get("count") or 0)
        weighted_score = float(row.get("weighted_score") or 0.0)
        current["mentions"] += mentions
        current["score_weighted_sum"] += weighted_score * max(1.0, mentions)
    theme_breakdown = []
    for group, vals in theme_group_rollup.items():
        mentions = float(vals.get("mentions") or 0.0)
        score_weighted_sum = float(vals.get("score_weighted_sum") or 0.0)
        theme_breakdown.append(
            {
                "theme_group": group,
                "mentions": int(round(mentions)),
                "weighted_score": round(score_weighted_sum / max(1.0, mentions), 4),
            }
        )
    theme_breakdown.sort(key=lambda row: (int(row.get("mentions") or 0), abs(float(row.get("weighted_score") or 0.0))), reverse=True)
    global_context = {
        "global_news_collected": global_news_collected,
        "top_global_themes": global_themes[:5],
        "theme_breakdown": theme_breakdown[:6],
        "high_impact_global_events": high_impact_global_events[:5],
        "source_refs": sorted(
            {
                str(row.get("source_id") or "").strip()
                for row in high_impact_global_events
                if str(row.get("source_id") or "").strip()
            }
        )[:6],
    }

    return {
        "events_total": len(bundle.announcements),
        "events_by_type": dict(sorted(events_by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
        "event_groups": event_groups,
        "sentiment_highlights": sentiment_highlights,
        "market": {
            "market_date": str(bundle.market_date) if bundle.market_date else None,
            "index_rows": bundle.index_rows,
            "fx_rows": bundle.fx_rows,
            "movers": movers,
            "losers": losers,
        },
        "global_context": global_context,
        "signal_intelligence": signal_summary,
    }
