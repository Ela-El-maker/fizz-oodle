from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import time as timer
from zoneinfo import ZoneInfo

from apps.agents.sentiment.aggregate import build_weekly_rows
from apps.agents.sentiment.email import build_subject, render_digest_html, send_digest_email
from apps.agents.sentiment.extract import company_name_for_ticker, ticker_company_map, extract_tickers
from apps.agents.sentiment.themes import (
    build_theme_summary_for_week,
    infer_kenya_relevance,
    infer_themes,
)
from apps.agents.sentiment.normalize import make_post_id, normalize_text, payload_hash, utc_now
from apps.agents.sentiment.registry import get_collector, get_source_configs
from apps.agents.sentiment.score_llm import llm_refine_sentiment
from apps.agents.sentiment.score_rules import MODEL_VERSION, score_text
from apps.scrape_core.dedupe import content_fingerprint
from apps.scrape_core.retry import classify_error_type
from apps.agents.sentiment.store import (
    fetch_mentions_for_window,
    fetch_prev_scores,
    get_digest,
    mark_source_failure,
    mark_source_success,
    source_can_run,
    upsert_digest,
    upsert_raw_post,
    upsert_ticker_mention,
    upsert_weekly_rows,
)
from apps.agents.sentiment.types import MentionScore
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.logger import get_logger
from apps.core.alpha_vantage import fetch_alpha_quote_batch
from apps.core.run_service import fail_run, finish_run, start_run
from apps.core.seed import seed_companies
from apps.reporting.composer.renderers import from_sentiment_summary

logger = get_logger(__name__)
settings = get_settings()


def _week_start_eat(today: date | None = None) -> date:
    if today is None:
        today = datetime.now(ZoneInfo("Africa/Nairobi")).date()
    return today - timedelta(days=today.weekday())


def _range_for_week(week_start: date) -> tuple[datetime, datetime]:
    eat = ZoneInfo("Africa/Nairobi")
    start_eat = datetime.combine(week_start, time.min, tzinfo=eat)
    end_eat = start_eat + timedelta(days=int(settings.SENTIMENT_WINDOW_DAYS))
    now_utc = utc_now()
    start_utc = start_eat.astimezone(timezone.utc)
    end_utc = min(end_eat.astimezone(timezone.utc), now_utc)
    return start_utc, end_utc


def _mood_summary(rows: list[dict]) -> tuple[str, float, str]:
    if not rows:
        return "No sentiment signals available for this week.", 0.0, "neutral"
    total_mentions = sum(max(0, int(r.get("mentions_count", 0))) for r in rows)
    if total_mentions <= 0:
        return "No sentiment signals available for this week.", 0.0, "neutral"

    weighted_bullish = 0.0
    weighted_bearish = 0.0
    for row in rows:
        mentions = max(0, int(row.get("mentions_count", 0)))
        if mentions <= 0:
            continue
        weight = mentions / total_mentions
        weighted_bullish += float(row.get("bullish_pct", 0.0)) * weight
        weighted_bearish += float(row.get("bearish_pct", 0.0)) * weight
    mood_score = round((weighted_bullish - weighted_bearish) / 10.0, 2)

    if mood_score > 3.0:
        return "Overall market mood is bullish this week.", mood_score, "bullish"
    if mood_score > 1.0:
        return "Overall market mood is cautiously bullish this week.", mood_score, "cautiously_bullish"
    if mood_score < -3.0:
        return "Overall market mood is bearish this week.", mood_score, "bearish"
    if mood_score < -1.0:
        return "Overall market mood is cautiously bearish this week.", mood_score, "cautiously_bearish"
    return "Overall market mood is neutral this week.", mood_score, "neutral"


def _build_human_summary(rows: list[dict], mood_score: float, mood_label: str) -> dict:
    if not rows:
        return {
            "headline": "No usable sentiment signal this week.",
            "plain_summary": "There were no valid market mentions this week, so sentiment interpretation is unavailable.",
            "bullets": ["No sentiment inputs were collected for this period."],
            "coverage": {"tickers_with_signal": 0, "total_tickers": 0},
            "leaders": {"bullish": [], "bearish": []},
            "momentum": {"improving": [], "deteriorating": []},
        }

    total_tickers = len(rows)
    rows_with_signal = [r for r in rows if int(r.get("mentions_count", 0)) > 0]
    tickers_with_signal = len(rows_with_signal)
    bullish_majority = 0
    bearish_majority = 0
    neutral_majority = 0
    weighted_conf_num = 0.0
    weighted_conf_den = 0

    for row in rows_with_signal:
        bull = float(row.get("bullish_pct", 0.0))
        bear = float(row.get("bearish_pct", 0.0))
        if bull > bear and bull > 50.0:
            bullish_majority += 1
        elif bear > bull and bear > 50.0:
            bearish_majority += 1
        else:
            neutral_majority += 1

        mentions = max(0, int(row.get("mentions_count", 0)))
        weighted_conf_num += float(row.get("confidence", 0.0)) * mentions
        weighted_conf_den += mentions

    avg_confidence = round(weighted_conf_num / weighted_conf_den, 3) if weighted_conf_den > 0 else 0.0

    bullish_ranked = sorted(
        rows_with_signal,
        key=lambda r: (float(r.get("bullish_pct", 0.0)), int(r.get("mentions_count", 0))),
        reverse=True,
    )
    bearish_ranked = sorted(
        rows_with_signal,
        key=lambda r: (float(r.get("bearish_pct", 0.0)), int(r.get("mentions_count", 0))),
        reverse=True,
    )
    improving_ranked = sorted(
        [r for r in rows_with_signal if (r.get("wow_delta") is not None and float(r.get("wow_delta")) > 0)],
        key=lambda r: float(r.get("wow_delta", 0.0)),
        reverse=True,
    )
    deteriorating_ranked = sorted(
        [r for r in rows_with_signal if (r.get("wow_delta") is not None and float(r.get("wow_delta")) < 0)],
        key=lambda r: float(r.get("wow_delta", 0.0)),
    )

    top_bull = bullish_ranked[:3]
    top_bear = bearish_ranked[:3]
    top_improving = improving_ranked[:3]
    top_deteriorating = deteriorating_ranked[:3]

    mood_phrase = mood_label.replace("_", " ")
    headline = (
        f"Market mood is {mood_phrase} "
        f"(score {mood_score:+.2f}) with signal across {tickers_with_signal}/{total_tickers} tracked tickers."
    )

    plain_summary = (
        f"Conversation coverage is {tickers_with_signal} of {total_tickers} tickers. "
        f"Bullish-majority tickers: {bullish_majority}, bearish-majority: {bearish_majority}, mixed/neutral: {neutral_majority}. "
        f"Weighted confidence is {avg_confidence:.3f}."
    )

    def _fmt_ticker(item: dict, field: str) -> str:
        return (
            f"{item.get('ticker')} ({item.get('company_name')}): "
            f"{float(item.get(field, 0.0)):.1f}% "
            f"on {int(item.get('mentions_count', 0))} mentions"
        )

    def _fmt_momentum(item: dict) -> str:
        return (
            f"{item.get('ticker')} ({item.get('company_name')}): "
            f"WoW {float(item.get('wow_delta', 0.0)):+.2f}pp"
        )

    bullish_line = (
        "Top bullish sentiment: " + "; ".join(_fmt_ticker(i, "bullish_pct") for i in top_bull)
        if top_bull
        else "Top bullish sentiment: no strong bullish leader this week."
    )
    bearish_line = (
        "Top bearish sentiment: " + "; ".join(_fmt_ticker(i, "bearish_pct") for i in top_bear)
        if top_bear
        else "Top bearish sentiment: no strong bearish leader this week."
    )
    improving_line = (
        "Momentum improving: " + "; ".join(_fmt_momentum(i) for i in top_improving)
        if top_improving
        else "Momentum improving: no material positive WoW shift detected."
    )
    deteriorating_line = (
        "Momentum deteriorating: " + "; ".join(_fmt_momentum(i) for i in top_deteriorating)
        if top_deteriorating
        else "Momentum deteriorating: no material negative WoW shift detected."
    )
    low_conf_watch = [
        f"{r.get('ticker')} ({float(r.get('confidence', 0.0)):.2f})"
        for r in sorted(rows_with_signal, key=lambda x: float(x.get("confidence", 0.0)))[:3]
        if float(r.get("confidence", 0.0)) < 0.60
    ]
    watchlist_line = (
        "Low-confidence watchlist: " + ", ".join(low_conf_watch)
        if low_conf_watch
        else "Low-confidence watchlist: none."
    )

    return {
        "headline": headline,
        "plain_summary": plain_summary,
        "bullets": [bullish_line, bearish_line, improving_line, deteriorating_line, watchlist_line],
        "coverage": {"tickers_with_signal": tickers_with_signal, "total_tickers": total_tickers},
        "leaders": {
            "bullish": [_fmt_ticker(i, "bullish_pct") for i in top_bull],
            "bearish": [_fmt_ticker(i, "bearish_pct") for i in top_bear],
        },
        "momentum": {
            "improving": [_fmt_momentum(i) for i in top_improving],
            "deteriorating": [_fmt_momentum(i) for i in top_deteriorating],
        },
    }


async def run_sentiment_pipeline(
    run_id: str | None = None,
    week_start_override: date | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
) -> dict:
    rid = await start_run("sentiment", run_id=run_id)

    week_start = week_start_override or _week_start_eat()
    from_dt, to_dt = _range_for_week(week_start)
    now_utc = utc_now()
    force_send_final = bool(force_send if force_send is not None else settings.SENTIMENT_FORCE_RESEND)

    metrics: dict = {
        "week_start": week_start.isoformat(),
        "sources": {},
        "mentions_created": 0,
        "tickers_covered": 0,
        "digest_sent": False,
        "digest_skipped": False,
        "digest_error": None,
        "llm_calls_count": 0,
        "llm_attempted_count": 0,
        "llm_fallback_failed_count": 0,
        "llm_skipped_budget_count": 0,
        "llm_skipped_breaker_count": 0,
        "llm_breaker_open": False,
        "llm_breaker_reason": None,
        "core_sources_passed": [],
        "core_sources_failed": [],
        "secondary_sources_failed": [],
        "alpha_context": {
            "enabled": bool(settings.SENTIMENT_ALPHA_ENRICH_ENABLED),
            "requested": 0,
            "received": 0,
            "failed": 0,
            "errors": {},
            "tickers": [],
        },
    }

    total_processed = 0
    raw_inserted = 0
    source_failures = 0
    source_successes = 0
    core_failures = 0
    core_successes = 0
    run_seen_content_fps: set[str] = set()
    contribution_counts: dict[str, int] = {}
    llm_failure_streak = 0
    llm_breaker_open = False
    llm_breaker_reason: str | None = None
    llm_max_calls = max(0, int(settings.SENTIMENT_LLM_MAX_CALLS_PER_RUN))
    llm_breaker_fail_threshold = max(1, int(settings.SENTIMENT_LLM_BREAKER_FAIL_THRESHOLD))

    try:
        await seed_companies()
        source_configs = get_source_configs()
        if not source_configs:
            raise ValueError("No sentiment sources enabled")

        async with get_session() as session:
            for source in source_configs:
                started = timer.perf_counter()
                source_metrics = {
                    "posts_found": 0,
                    "posts_inserted": 0,
                    "items_found": 0,
                    "items_inserted": 0,
                    "duplicates": 0,
                    "duration_ms": 0,
                    "error_type": None,
                    "error": None,
                    "status": "success",
                    "cache_hit": False,
                    "not_modified_count": 0,
                    "rate_limited_count": 0,
                    "breaker_state": "closed",
                }
                is_core = bool(source.required_for_success or source.tier == "core")
                try:
                    if not await source_can_run(
                        session=session,
                        source_id=source.source_id,
                        breaker_enabled=settings.SOURCE_BREAKER_ENABLED,
                        now_utc=now_utc,
                    ):
                        source_metrics["error"] = "source_breaker_open"
                        source_metrics["error_type"] = "source_breaker_open"
                        source_metrics["status"] = "fail"
                        source_metrics["breaker_state"] = "open"
                        source_failures += 1
                        if is_core:
                            core_failures += 1
                            metrics["core_sources_failed"].append(source.source_id)
                        else:
                            metrics["secondary_sources_failed"].append(source.source_id)
                        metrics["sources"][source.source_id] = source_metrics
                        continue

                    if source.requires_auth and source.auth_env_key:
                        token = getattr(settings, source.auth_env_key, "")
                        if not token:
                            source_metrics["status"] = "skipped"
                            source_metrics["error_type"] = "missing_key"
                            source_metrics["error"] = f"missing {source.auth_env_key}"
                            metrics["sources"][source.source_id] = source_metrics
                            continue

                    collector = get_collector(source)
                    posts = await collector(source, from_dt, to_dt)
                    posts = posts[: source.max_items_per_run]
                    source_metrics["posts_found"] = len(posts)
                    source_metrics["items_found"] = len(posts)

                    latest_published: datetime | None = None

                    for post in posts:
                        normalized_title = normalize_text(post.title)
                        normalized_content = normalize_text(post.content)
                        post_content_fp = content_fingerprint(normalized_title, normalized_content)
                        if post_content_fp in run_seen_content_fps:
                            source_metrics["duplicates"] += 1
                            continue
                        run_seen_content_fps.add(post_content_fp)

                        post_id = make_post_id(
                            source_id=source.source_id,
                            canonical_url=post.canonical_url,
                            title=normalized_title,
                            content=normalized_content,
                            published_at=post.published_at,
                        )
                        base_text = f"{normalized_title} {normalized_content}".strip()
                        post_themes = infer_themes(base_text, source_theme=source.theme)
                        kenya_relevance = max(
                            [
                                infer_kenya_relevance(
                                    theme=theme,
                                    text=base_text,
                                    scope=source.scope,
                                    source_weight=float(source.weight),
                                )
                                for theme in post_themes
                            ]
                            or [1.0 if source.scope != "global_outside" else 0.25]
                        )
                        payload = dict(post.raw_payload or {})
                        payload.update(
                            {
                                "scope": source.scope or "kenya_extended",
                                "market_region": source.market_region or "kenya",
                                "signal_class": source.signal_class or "news_signal",
                                "theme": (post_themes[0] if post_themes else source.theme),
                                "themes": post_themes,
                                "kenya_relevance": round(float(kenya_relevance), 3),
                            }
                        )
                        post.raw_payload = payload
                        inserted = await upsert_raw_post(session, post_id=post_id, post=post)
                        total_processed += 1
                        if not inserted:
                            source_metrics["duplicates"] += 1
                            continue

                        raw_inserted += 1
                        source_metrics["posts_inserted"] += 1
                        source_metrics["items_inserted"] += 1
                        contribution_counts[source.source_id] = int(contribution_counts.get(source.source_id) or 0) + 1
                        if post.published_at is not None:
                            if latest_published is None or post.published_at > latest_published:
                                latest_published = post.published_at

                        tickers = extract_tickers(f"{normalized_title} {normalized_content}")
                        for ticker in tickers:
                            scored = score_text(f"{normalized_title} {normalized_content}")
                            score = float(scored.score)
                            label = scored.label
                            confidence = float(scored.confidence)
                            reasons = dict(scored.reasons)
                            llm_used = False

                            if confidence < float(settings.SENTIMENT_CONFIDENCE_THRESHOLD):
                                allow_llm = True
                                if llm_breaker_open:
                                    allow_llm = False
                                    metrics["llm_skipped_breaker_count"] += 1
                                elif int(metrics["llm_attempted_count"]) >= llm_max_calls:
                                    allow_llm = False
                                    metrics["llm_skipped_budget_count"] += 1

                                if allow_llm:
                                    metrics["llm_attempted_count"] += 1
                                    llm = await llm_refine_sentiment(
                                        text=f"{normalized_title}\n{normalized_content}",
                                        ticker=ticker,
                                    )
                                    if llm is not None:
                                        score = llm.score
                                        label = llm.label
                                        confidence = max(confidence, llm.confidence)
                                        reasons["llm_reason"] = llm.reason
                                        llm_used = True
                                        metrics["llm_calls_count"] += 1
                                        llm_failure_streak = 0
                                    else:
                                        metrics["llm_fallback_failed_count"] += 1
                                        llm_failure_streak += 1
                                        if llm_failure_streak >= llm_breaker_fail_threshold:
                                            llm_breaker_open = True
                                            llm_breaker_reason = "llm_failure_threshold"

                            mention = MentionScore(
                                ticker=ticker,
                                company_name=company_name_for_ticker(ticker),
                                sentiment_score=score,
                                sentiment_label=label,
                                confidence=round(confidence, 3),
                                source_weight=float(source.weight),
                                reasons=reasons,
                                model_version=MODEL_VERSION,
                                llm_used=llm_used,
                                scored_at=utc_now(),
                            )
                            created = await upsert_ticker_mention(
                                session,
                                post_id=post_id,
                                mention=mention,
                                source_id=source.source_id,
                            )
                            if created:
                                metrics["mentions_created"] += 1

                    await mark_source_success(
                        session=session,
                        source_id=source.source_id,
                        metrics=source_metrics,
                        now_utc=now_utc,
                    )
                    source_successes += 1
                    if is_core:
                        core_successes += 1
                        metrics["core_sources_passed"].append(source.source_id)
                    if latest_published is not None:
                        age_hours = max(0.0, (now_utc - latest_published).total_seconds() / 3600.0)
                        source_metrics["freshness_max_age_hours"] = round(age_hours, 2)

                except Exception as exc:  # noqa: PERF203
                    source_failures += 1
                    raw_error = str(exc)
                    if ":" in raw_error and raw_error.split(":", 1)[0].isidentifier():
                        inferred_error_type = raw_error.split(":", 1)[0]
                    else:
                        inferred_error_type = classify_error_type(exc)
                    source_metrics["error"] = raw_error
                    source_metrics["error_type"] = inferred_error_type
                    source_metrics["status"] = "fail"
                    if inferred_error_type == "rate_limited":
                        source_metrics["rate_limited_count"] = int(source_metrics.get("rate_limited_count") or 0) + 1
                    if is_core:
                        core_failures += 1
                        metrics["core_sources_failed"].append(source.source_id)
                    else:
                        metrics["secondary_sources_failed"].append(source.source_id)
                    await mark_source_failure(
                        session=session,
                        source_id=source.source_id,
                        error=raw_error,
                        error_type=inferred_error_type,
                        now_utc=now_utc,
                        fail_threshold=settings.SOURCE_FAIL_THRESHOLD,
                        cooldown_minutes=settings.SOURCE_COOLDOWN_MINUTES,
                    )
                    logger.exception("sentiment_source_failed", run_id=rid, source_id=source.source_id, error=raw_error)
                finally:
                    source_metrics["duration_ms"] = int((timer.perf_counter() - started) * 1000)
                    metrics["sources"][source.source_id] = source_metrics
                    await session.commit()

            mentions = await fetch_mentions_for_window(session, from_dt=from_dt, to_dt=to_dt)
            prev_scores = await fetch_prev_scores(session, previous_week=week_start - timedelta(days=7))
            weekly_rows = build_weekly_rows(
                week_start=week_start,
                mentions=mentions,
                ticker_company=ticker_company_map(),
                prev_scores=prev_scores,
            )
            source_weight_map = {cfg.source_id: float(cfg.weight) for cfg in source_configs}
            theme_summary = await build_theme_summary_for_week(
                session,
                week_start=week_start,
                source_weights=source_weight_map,
                window_days=int(settings.SENTIMENT_WINDOW_DAYS),
            )
            metrics["theme_summary"] = {
                "week_start": week_start.isoformat(),
                "items": theme_summary,
            }
            alpha_context_by_ticker: dict[str, dict] = {}
            if settings.SENTIMENT_ALPHA_ENRICH_ENABLED and weekly_rows:
                ranked = sorted(
                    [row for row in weekly_rows if int(row.mentions_count or 0) >= int(settings.SENTIMENT_ALPHA_MIN_MENTIONS)],
                    key=lambda row: int(row.mentions_count or 0),
                    reverse=True,
                )
                alpha_tickers = [row.ticker for row in ranked]
                alpha_context_by_ticker, alpha_meta = await fetch_alpha_quote_batch(
                    alpha_tickers,
                    exchange="NSE",
                    target_date=week_start,
                    max_tickers=int(settings.SENTIMENT_ALPHA_MAX_TICKERS_PER_RUN),
                )
                metrics["alpha_context"] = {
                    "enabled": True,
                    "requested": int(alpha_meta.get("requested") or 0),
                    "received": int(alpha_meta.get("received") or 0),
                    "failed": int(alpha_meta.get("failed") or 0),
                    "errors": alpha_meta.get("errors") or {},
                    "tickers": sorted(alpha_context_by_ticker.keys()),
                }
            metrics["tickers_covered"] = len([r for r in weekly_rows if r.mentions_count > 0])
            weekly_inserted = await upsert_weekly_rows(session, rows=weekly_rows)

            rows_payload = [
                {
                    "ticker": row.ticker,
                    "company_name": row.company_name,
                    "mentions_count": row.mentions_count,
                    "bullish_pct": row.bullish_pct,
                    "bearish_pct": row.bearish_pct,
                    "neutral_pct": row.neutral_pct,
                    "weighted_score": row.weighted_score,
                    "confidence": row.confidence,
                    "notable_quotes": row.notable_quotes,
                    "wow_delta": row.wow_delta,
                    "alpha_context": alpha_context_by_ticker.get(row.ticker),
                }
                for row in weekly_rows
            ]

            mood_text, mood_score, mood_label = _mood_summary(rows_payload)
            metrics["market_mood_score"] = mood_score
            metrics["market_mood_label"] = mood_label
            human_summary = _build_human_summary(rows_payload, mood_score=mood_score, mood_label=mood_label)
            human_summary_v2 = from_sentiment_summary(summary=human_summary, metrics=metrics)
            metrics["human_summary"] = human_summary
            metrics["human_summary_v2"] = human_summary_v2

            subject = build_subject(week_start)
            html = render_digest_html(
                week_start=week_start,
                rows=rows_payload,
                mood=mood_text,
                human_summary=human_summary,
                human_summary_v2=human_summary_v2,
            )

            existing_digest = await get_digest(session, week_start=week_start)
            legacy_enabled = (not settings.EMAIL_EXEC_DIGEST_ENABLED) or bool(settings.EMAIL_EXEC_DIGEST_PARALLEL_LEGACY) or force_send_final
            should_send = legacy_enabled
            if existing_digest and existing_digest.email_sent_at and not force_send_final:
                should_send = False
                metrics["digest_skipped"] = True
            if not legacy_enabled:
                metrics["digest_skipped"] = True
                metrics["digest_skipped_reason"] = "legacy_cutover_enabled"

            digest_status = "generated"
            email_sent_at = None
            email_error = None
            if should_send:
                if email_recipients_override:
                    sent, err = send_digest_email(
                        subject=subject,
                        html=html,
                        recipients=email_recipients_override,
                    )
                else:
                    sent, err = send_digest_email(subject=subject, html=html)
                metrics["digest_sent"] = sent
                metrics["digest_error"] = err
                if sent:
                    digest_status = "sent"
                    email_sent_at = utc_now()
                else:
                    digest_status = "fail"
                    email_error = err
            else:
                digest_status = "sent" if existing_digest and existing_digest.email_sent_at else "generated"
                email_sent_at = existing_digest.email_sent_at if existing_digest else None

            await upsert_digest(
                session=session,
                week_start=week_start,
                subject=subject,
                html_content=html,
                payload_hash=payload_hash(html),
                status=digest_status,
                metrics={**metrics, "weekly_rows_inserted": weekly_inserted},
                email_sent_at=email_sent_at,
                email_error=email_error,
            )
            await session.commit()

        status = "success"
        if core_failures > 0:
            status = "partial" if source_successes > 0 else "fail"
        elif source_failures and not source_successes:
            status = "fail"
        if metrics.get("digest_error"):
            status = "fail" if status == "success" else "partial"
        metrics["core_sources_passed_count"] = core_successes
        metrics["core_sources_failed_count"] = core_failures
        metrics["llm_breaker_open"] = llm_breaker_open
        metrics["llm_breaker_reason"] = llm_breaker_reason
        if raw_inserted > 0:
            metrics["source_contribution_pct"] = {
                sid: round((count / raw_inserted) * 100.0, 2) for sid, count in sorted(contribution_counts.items())
            }
        else:
            metrics["source_contribution_pct"] = {}
        if status == "success":
            metrics["status_reason"] = "all_core_sources_passed"
        elif status == "partial":
            metrics["status_reason"] = "core_or_digest_degradation"
        else:
            metrics["status_reason"] = "critical_source_or_digest_failure"

        await finish_run(
            run_id=rid,
            status=status,
            records_processed=total_processed,
            records_new=raw_inserted,
            errors_count=source_failures + (1 if metrics.get("digest_error") else 0),
            metrics=metrics,
            error_message=metrics.get("digest_error"),
        )

        return {
            "run_id": rid,
            "status": status,
            "records_processed": total_processed,
            "records_new": raw_inserted,
            "metrics": metrics,
        }
    except Exception as exc:
        logger.exception("run_failed", run_id=rid, agent_name="sentiment", error=str(exc))
        await fail_run(
            run_id=rid,
            error_message=str(exc),
            metrics=metrics,
            records_processed=total_processed,
            records_new=raw_inserted,
            errors_count=source_failures + 1,
        )
        raise
