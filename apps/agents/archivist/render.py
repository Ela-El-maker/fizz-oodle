from __future__ import annotations

import hashlib
import json
from datetime import date

from jinja2 import Environment, FileSystemLoader


def make_archive_payload_hash(run_type: str, period_key: date, payload: dict, html: str) -> str:
    canonical = {
        "run_type": run_type,
        "period_key": period_key.isoformat(),
        "payload": payload,
        "html": html,
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def render_archive_html(*, run_type: str, period_key: date, payload: dict, human_summary_v2: dict | None = None) -> str:
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("archivist_report.html")
    return template.render(
        run_type=run_type,
        period_key=period_key.isoformat(),
        payload=payload,
        human_summary_v2=human_summary_v2 or {},
    )
