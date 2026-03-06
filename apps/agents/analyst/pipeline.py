from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from apps.agents.analyst.email import send_report_email
from apps.agents.analyst.features import build_features
from apps.agents.analyst.inputs import load_inputs, resolve_period_key
from apps.agents.analyst.llm import polish_overview
from apps.agents.analyst.render import make_payload_hash, render_report_html
from apps.agents.analyst.rules import build_payload, build_subject
from apps.agents.analyst.store import get_report_by_key, should_send, upsert_report
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.event_schemas import AnalystReportGeneratedV1
from apps.core.events import publish_analyst_report_generated
from apps.core.logger import get_logger
from apps.core.run_service import fail_run, finish_run, start_run
from apps.reporting.composer.renderers import from_report_summary

logger = get_logger(__name__)
settings = get_settings()


def _allowed_report_types() -> set[str]:
    raw = settings.ANALYST_REPORT_TYPES or "daily,weekly"
    parsed = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return parsed or {"daily", "weekly"}


def _normalize_report_type(report_type: str | None) -> str:
    value = (report_type or "daily").strip().lower()
    if value not in _allowed_report_types():
        raise ValueError(f"Unsupported report_type={value}")
    return value


def _normalize_period_key(report_type: str, period_key: date | None) -> date:
    resolved = resolve_period_key(report_type=report_type, period_key=period_key)
    if report_type == "weekly":
        return resolved - timedelta(days=resolved.weekday())
    return resolved


def _build_report_human_summary(*, payload, metrics: dict, upstream_quality: dict) -> dict:
    overview = [str(line).strip() for line in (payload.overview or []) if str(line).strip()]
    watch = [str(line).strip() for line in (payload.what_to_watch or []) if str(line).strip()]
    data_quality = [str(line).strip() for line in (payload.data_quality or []) if str(line).strip()]

    headline = overview[0] if overview else "Analyst synthesis generated for the selected period."
    plain_summary = " ".join(overview[:2]).strip() if overview else "No overview narrative was produced."

    tickers_covered = int(metrics.get("tickers_covered") or 0)
    events_included = int(metrics.get("events_included") or 0)
    quality_score = float(upstream_quality.get("score") or 0.0)
    degraded = bool(metrics.get("degraded"))
    feedback_applied = bool(metrics.get("feedback_applied"))
    feedback_coverage_pct = float(metrics.get("feedback_coverage_pct") or 0.0)

    summary_bullets: list[str] = []
    summary_bullets.append(f"Coverage: {tickers_covered} tickers, {events_included} announcements.")
    summary_bullets.append(f"Upstream quality score: {quality_score:.2f}/100.")
    summary_bullets.append(
        f"Archivist feedback: {'applied' if feedback_applied else 'missing'} "
        f"(coverage {feedback_coverage_pct:.2f}%)."
    )
    if degraded:
        summary_bullets.append("Run mode: degraded (some upstream inputs were missing or low quality).")
    summary_bullets.extend(watch[:3])
    summary_bullets.extend(data_quality[:2])

    return {
        "headline": headline,
        "plain_summary": plain_summary,
        "bullets": summary_bullets,
        "coverage": {
            "tickers_covered": tickers_covered,
            "events_included": events_included,
            "upstream_quality_score": quality_score,
        },
        "flags": {
            "degraded": degraded,
            "llm_used": bool(metrics.get("llm_used")),
            "llm_error": metrics.get("llm_error"),
        },
    }


async def run_analyst_pipeline(
    run_id: str | None = None,
    report_type: str | None = None,
    period_key: date | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
) -> dict:
    rid = await start_run("analyst", run_id=run_id)

    normalized_report_type = _normalize_report_type(report_type)
    normalized_period_key = _normalize_period_key(normalized_report_type, period_key)
    force_send_final = bool(force_send if force_send is not None else settings.ANALYST_FORCE_RESEND)

    metrics: dict = {
        "report_type": normalized_report_type,
        "period_key": normalized_period_key.isoformat(),
        "input_chain": "A+B+C",
        "upstream": {"available": {}, "ids": {}},
        "degraded": False,
        "events_included": 0,
        "tickers_covered": 0,
        "email_sent": False,
        "email_skipped": False,
        "email_error": None,
        "llm_used": False,
        "llm_error": None,
        "feedback_applied": False,
        "feedback_coverage_pct": 0.0,
        "feedback_timestamp_used": None,
        "feedback_version": None,
        "decision_trace": [],
    }

    processed = 0
    records_new = 0

    try:
        async with get_session() as session:
            bundle = await load_inputs(
                session=session,
                report_type=normalized_report_type,
                period_key=normalized_period_key,
            )
            upstream_quality = bundle.upstream_quality or {}
            quality_score = float(upstream_quality.get("score") or 0.0)
            if quality_score < 70.0 and "upstream_quality_low" not in bundle.degraded_reasons:
                bundle.degraded_reasons.append("upstream_quality_low")
            feedback_warning = False
            if "archivist_feedback_unavailable" in bundle.degraded_reasons:
                bundle.degraded_reasons = [r for r in bundle.degraded_reasons if r != "archivist_feedback_unavailable"]
                feedback_warning = True
            features = build_features(bundle)
            feedback_info = ((features.get("signal_intelligence") or {}).get("feedback") or {})
            feedback_applied = bool(feedback_info.get("applied"))
            feedback_coverage_pct = float(feedback_info.get("coverage_pct") or 0.0)
            feedback_timestamp = feedback_info.get("feedback_timestamp")
            feedback_version = (
                f"patterns:{int(feedback_info.get('patterns') or 0)}"
                f"|impacts:{int(feedback_info.get('impacts') or 0)}"
            )
            decision_traces = list((features.get("signal_intelligence") or {}).get("decision_traces") or [])

            payload = build_payload(
                bundle=bundle,
                features=features,
                min_confidence_for_strong_language=float(settings.ANALYST_MIN_CONFIDENCE_FOR_STRONG_LANGUAGE),
            )

            polished_overview, llm_used, llm_error = await polish_overview(payload.overview, normalized_report_type)
            payload.overview = polished_overview
            metrics["llm_used"] = bool(llm_used)
            metrics["llm_error"] = llm_error

            subject = build_subject(normalized_report_type, normalized_period_key)
            existing = await get_report_by_key(
                session,
                report_type=normalized_report_type,
                period_key=normalized_period_key,
            )
            send_now, skipped = should_send(existing=existing, force_send=force_send_final)

            report_status = "generated"
            email_sent_at = None
            email_error = None

            payload_dict = asdict(payload)
            metrics["global_context"] = payload_dict.get("global_context") if isinstance(payload_dict, dict) else {}

            processed = len(bundle.announcements) + len(bundle.sentiment_rows) + len(bundle.movers) + len(bundle.losers)
            records_new = 1 if existing is None else 0

            metrics["degraded"] = payload.degraded
            metrics["events_included"] = len(bundle.announcements)
            metrics["tickers_covered"] = len(
                {
                    *[row["ticker"] for row in bundle.sentiment_rows],
                    *[item["ticker"] for item in bundle.announcements if item.get("ticker")],
                }
            )
            metrics["upstream"]["available"] = {
                "briefing": bool(bundle.inputs_summary.get("briefing", {}).get("available")),
                "announcements": bool(bundle.inputs_summary.get("announcements", {}).get("available")),
                "sentiment": bool(bundle.inputs_summary.get("sentiment", {}).get("available")),
                "archivist_feedback": bool(bundle.inputs_summary.get("archivist_feedback", {}).get("available")),
            }
            metrics["upstream"]["ids"] = {
                "briefing_date": bundle.inputs_summary.get("briefing", {}).get("briefing_date"),
                "sentiment_week_start": bundle.inputs_summary.get("sentiment", {}).get("week_start"),
                "market_date": bundle.inputs_summary.get("market_date"),
            }
            metrics["upstream_quality"] = upstream_quality
            metrics["feedback_applied"] = feedback_applied
            metrics["feedback_coverage_pct"] = round(feedback_coverage_pct, 2)
            metrics["feedback_timestamp_used"] = feedback_timestamp
            metrics["feedback_version"] = feedback_version
            if settings.ANALYST_USE_ARCHIVIST_FEEDBACK:
                metrics["feedback_warning"] = "archivist_feedback_missing" if (feedback_warning or not feedback_applied) else None
            else:
                metrics["feedback_warning"] = None
            metrics["decision_trace"] = decision_traces[:10]
            metrics["human_summary"] = _build_report_human_summary(
                payload=payload,
                metrics=metrics,
                upstream_quality=upstream_quality,
            )
            metrics["human_summary_v2"] = from_report_summary(
                summary=metrics.get("human_summary") if isinstance(metrics.get("human_summary"), dict) else {},
                metrics=metrics,
            )

            html = render_report_html(payload, human_summary_v2=metrics["human_summary_v2"])
            p_hash = make_payload_hash(payload, html)

            if send_now:
                if email_recipients_override:
                    sent, err = send_report_email(
                        subject=subject,
                        html=html,
                        recipients=email_recipients_override,
                    )
                else:
                    sent, err = send_report_email(subject=subject, html=html)
                metrics["email_sent"] = sent
                metrics["email_error"] = err
                if sent:
                    report_status = "sent"
                    email_sent_at = datetime.now(timezone.utc)
                else:
                    report_status = "fail"
                    email_error = err
            else:
                metrics["email_skipped"] = True
                report_status = "sent"
                email_sent_at = existing.email_sent_at if existing else None

            report = await upsert_report(
                session=session,
                report_type=normalized_report_type,
                period_key=normalized_period_key,
                subject=subject,
                html_content=html,
                json_payload=payload_dict,
                inputs_summary=bundle.inputs_summary,
                metrics=metrics,
                payload_hash=p_hash,
                status=report_status,
                email_sent_at=email_sent_at,
                email_error=email_error,
                llm_used=bool(llm_used),
                degraded=payload.degraded,
            )
            await session.commit()

            try:
                event_payload = AnalystReportGeneratedV1(
                    report_id=str(report.report_id),
                    report_type=normalized_report_type,  # type: ignore[arg-type]
                    period_key=normalized_period_key,
                    degraded=bool(payload.degraded),
                    generated_at=report.generated_at,
                ).model_dump(mode="json")
                await publish_analyst_report_generated(event_payload)
            except Exception as e:  # noqa: PERF203
                logger.warning("analyst_event_publish_failed", run_id=rid, error=str(e))

            run_status = "partial" if payload.degraded else "success"
            if email_error:
                run_status = "fail"
            if run_status == "success":
                metrics["status_reason"] = "upstream_quality_ok"
            elif run_status == "partial":
                metrics["status_reason"] = "degraded_upstream_inputs"
            else:
                metrics["status_reason"] = "report_or_email_failure"

            await finish_run(
                rid,
                status=run_status,
                records_processed=processed,
                records_new=records_new,
                errors_count=len(bundle.degraded_reasons) + (1 if email_error else 0),
                metrics=metrics,
                error_message=email_error,
            )

        return {
            "run_id": rid,
            "status": run_status,
            "report_type": normalized_report_type,
            "period_key": normalized_period_key.isoformat(),
            "metrics": metrics,
        }
    except Exception as exc:  # noqa: PERF203
        logger.exception("run_failed", run_id=rid, agent_name="analyst", error=str(exc))
        await fail_run(
            rid,
            error_message=str(exc),
            metrics=metrics,
            records_processed=processed,
            records_new=records_new,
            errors_count=1,
        )
        raise
