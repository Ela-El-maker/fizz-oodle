from __future__ import annotations

from datetime import date

from apps.agents.analyst.types import AnalystPayload, InputsBundle


def build_subject(report_type: str, period_key: date) -> str:
    if report_type == "weekly":
        return f"🧠 Weekly Analyst Note — Week of {period_key.isoformat()}"
    return f"🧾 NSE Analyst Note — {period_key.isoformat()}"


def _strong_descriptor(confidence: float, threshold: float) -> str:
    if confidence >= threshold:
        return "strong"
    return "low-confidence"


def build_payload(
    bundle: InputsBundle,
    features: dict,
    min_confidence_for_strong_language: float,
) -> AnalystPayload:
    report_type = bundle.report_type
    period_key = bundle.period_key

    overview: list[str] = []

    if features["market"]["movers"]:
        top = features["market"]["movers"][0]
        overview.append(
            f"Top gainer: {top['ticker']} ({top['pct_change']:+.2f}% on market date {features['market']['market_date']})."
        )
    else:
        overview.append("Market movers unavailable for this report window.")

    if features["events_total"] > 0:
        top_group = features["event_groups"][0]
        overview.append(
            f"Corporate events: {features['events_total']} items, led by {top_group['ticker']} ({top_group['count']} items)."
        )
    else:
        overview.append("No new corporate announcements in the selected window.")

    if features["sentiment_highlights"]:
        lead = features["sentiment_highlights"][0]
        strength = _strong_descriptor(float(lead.get("confidence") or 0.0), min_confidence_for_strong_language)
        overview.append(
            f"Sentiment highlight: {lead['ticker']} score {float(lead['weighted_score']):+.3f} ({strength}, confidence {float(lead['confidence']):.3f})."
        )
    else:
        overview.append("Sentiment highlights unavailable for the selected week.")

    signal_intel = features.get("signal_intelligence") or {}
    global_context = features.get("global_context") or {}
    top_convergence = (signal_intel.get("top_convergence") or [])[:3]
    if top_convergence:
        lead_conv = top_convergence[0]
        overview.append(
            "Convergence lead: "
            f"{lead_conv.get('ticker')} {lead_conv.get('convergence_direction')} "
            f"(score {int(lead_conv.get('convergence_score') or 0)}, confidence {float(lead_conv.get('confidence_pct') or 0.0):.1f}%)."
        )
    if signal_intel.get("market_regime"):
        overview.append(f"Market regime estimate: {signal_intel.get('market_regime')}.")

    data_quality: list[str] = []
    if bundle.degraded_reasons:
        data_quality.append("Report generated in degraded mode due to missing or fallback upstream inputs.")
        for reason in bundle.degraded_reasons:
            data_quality.append(f"- {reason}")
    else:
        data_quality.append("All upstream inputs were available.")

    what_to_watch: list[str] = []
    high_impact_types = {"trading_suspension", "profit_warning", "earnings"}
    for group in features["event_groups"]:
        if any(t in high_impact_types for t in group["types"]):
            what_to_watch.append(
                f"{group['ticker']}: high-impact filing(s) detected ({', '.join(group['types'])})."
            )

    for row in features["sentiment_highlights"]:
        if abs(float(row.get("weighted_score") or 0.0)) >= 0.25 and float(row.get("confidence") or 0.0) >= 0.5:
            what_to_watch.append(
                f"{row['ticker']}: sentiment shift {float(row.get('wow_delta') or 0.0):+.3f} WoW with score {float(row['weighted_score']):+.3f}."
            )

    archivist_feedback = bundle.archivist_feedback or {"patterns": [], "impacts": [], "archive_latest_weekly": None}
    patterns_count = len(archivist_feedback.get("patterns") or [])
    if patterns_count:
        what_to_watch.append(
            f"Archivist feedback: {patterns_count} active confirmed pattern(s) available for reference."
        )

    for row in top_convergence:
        what_to_watch.append(
            f"{row.get('ticker')}: convergence {row.get('convergence_direction')} "
            f"(score {int(row.get('convergence_score') or 0)}, confidence {float(row.get('confidence_pct') or 0.0):.1f}%)."
        )
    for row in (signal_intel.get("anomalies") or [])[:3]:
        anomaly_text = ", ".join(row.get("anomalies") or [])
        what_to_watch.append(
            f"{row.get('ticker')}: anomaly {anomaly_text} "
            f"(confidence {float(row.get('confidence_pct') or 0.0):.1f}%)."
        )

    calibration_feedback = bundle.calibration_feedback or {}
    if calibration_feedback:
        target = float(calibration_feedback.get("nominal_target_pct") or 80.0)
        actual = float(calibration_feedback.get("actual_accuracy_pct") or 0.0)
        what_to_watch.append(
            f"Calibration note: nominal {target:.1f}% vs observed {actual:.1f}% "
            f"({actual - target:+.1f}pp)."
        )

    if not what_to_watch:
        what_to_watch.append("No exceptional watch flags detected; monitor routine disclosures and sentiment drift.")

    high_impact_global = global_context.get("high_impact_global_events") if isinstance(global_context, dict) else []
    if isinstance(high_impact_global, list) and high_impact_global:
        lead = high_impact_global[0]
        lead_theme = str(lead.get("theme") or "global_macro").replace("_", " ")
        lead_score = int(lead.get("kenya_impact_score") or 0)
        what_to_watch.append(
            f"Global context: {lead_theme} transmission risk (Kenya impact {lead_score}/100) is elevated."
        )

    title = "Weekly Analyst Synthesis" if report_type == "weekly" else "Daily Analyst Synthesis"

    return AnalystPayload(
        report_type=report_type,
        period_key=period_key.isoformat(),
        title=title,
        overview=overview,
        market_snapshot=features["market"],
        key_events=bundle.announcements,
        sentiment_pulse=features["sentiment_highlights"],
        archivist_feedback=archivist_feedback,
        signal_intelligence=signal_intel,
        global_context=global_context if isinstance(global_context, dict) else {},
        what_to_watch=what_to_watch[:12],
        data_quality=data_quality,
        degraded=bool(bundle.degraded_reasons),
    )
