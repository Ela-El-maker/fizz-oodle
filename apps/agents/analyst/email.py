from __future__ import annotations

from typing import Iterable

from apps.core.email_service import EmailService


def send_report_email(
    subject: str,
    html: str,
    recipients: Iterable[str] | str | None = None,
) -> tuple[bool, str | None]:
    result = EmailService().send_result(subject=subject, html=html, recipients=recipients)
    return bool(result.ok), result.error
