from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from jinja2 import Environment, FileSystemLoader

from apps.core.email_service import EmailService
from apps.core.models import Announcement


def _group_rows(announcements: list[Announcement]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in announcements:
        ticker = row.ticker or "UNKNOWN"
        key = f"{ticker}:{row.company_name or 'Unknown'}"
        entry = grouped.setdefault(
            key,
            {
                "ticker": ticker,
                "company": row.company_name or "Unknown",
                "items": [],
            },
        )
        entry["items"].append(
            {
                "announcement_id": row.announcement_id,
                "headline": row.headline,
                "type": row.announcement_type,
                "date": row.announcement_date.isoformat() if row.announcement_date else None,
                "source": row.source_id,
                "url": row.url,
                "details": row.details,
            }
        )

    # deterministic order for tests + consistent emails
    return sorted(grouped.values(), key=lambda g: (g["ticker"], g["company"]))


def render_announcements_email(announcements: list[Announcement], run_id: str) -> tuple[str, str]:
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("announcements.html")

    groups = _group_rows(announcements)
    count = sum(len(group["items"]) for group in groups)
    date_str = datetime.utcnow().date().isoformat()
    subject = f"🚨 High-Impact NSE Alerts ({count}) — {date_str}"
    html = template.render(date=date_str, count=count, groups=groups, run_id=run_id, human_summary={}, human_summary_v2={})
    return subject, html


def send_announcements_email(
    announcements: list[Announcement],
    run_id: str,
    human_summary: dict | None = None,
    human_summary_v2: dict | None = None,
    recipients: Iterable[str] | str | None = None,
) -> tuple[bool, str | None]:
    if not announcements:
        return False, None

    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("announcements.html")
    groups = _group_rows(announcements)
    count = sum(len(group["items"]) for group in groups)
    date_str = datetime.utcnow().date().isoformat()
    subject = f"🚨 High-Impact NSE Alerts ({count}) — {date_str}"
    html = template.render(
        date=date_str,
        count=count,
        groups=groups,
        run_id=run_id,
        human_summary=human_summary or {},
        human_summary_v2=human_summary_v2 or {},
    )
    result = EmailService().send_result(subject=subject, html=html, recipients=recipients)
    return bool(result.ok), result.error
