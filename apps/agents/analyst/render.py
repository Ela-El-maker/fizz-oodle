from __future__ import annotations

import hashlib
import json

from jinja2 import Environment, FileSystemLoader

from apps.agents.analyst.types import AnalystPayload


def render_report_html(payload: AnalystPayload, human_summary_v2: dict | None = None) -> str:
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("analyst_report.html")
    return template.render(payload=payload, human_summary_v2=human_summary_v2 or {})


def make_payload_hash(payload: AnalystPayload, html: str) -> str:
    canonical = {
        "report_type": payload.report_type,
        "period_key": payload.period_key,
        "overview": payload.overview,
        "market_snapshot": payload.market_snapshot,
        "key_events": payload.key_events,
        "sentiment_pulse": payload.sentiment_pulse,
        "archivist_feedback": payload.archivist_feedback,
        "signal_intelligence": payload.signal_intelligence,
        "global_context": payload.global_context,
        "what_to_watch": payload.what_to_watch,
        "data_quality": payload.data_quality,
        "degraded": payload.degraded,
        "html": html,
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
