from __future__ import annotations

from datetime import date
from typing import Iterable

from apps.core.email_service import EmailService


def build_archive_subject(run_type: str, period_key: date) -> str:
    if run_type == "monthly":
        return f"📚 Monthly Archive Intelligence — {period_key.isoformat()}"
    return f"📚 Weekly Archive Intelligence — Week of {period_key.isoformat()}"


def send_archive_email(
    subject: str,
    html: str,
    recipients: Iterable[str] | str | None = None,
) -> tuple[bool, str | None]:
    result = EmailService().send_result(subject=subject, html=html, recipients=recipients)
    return bool(result.ok), result.error
