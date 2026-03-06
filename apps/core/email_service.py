from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import smtplib
import ssl
from typing import Iterable

from apps.core.config import get_settings
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


def _parse_recipients(value: str) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


@dataclass
class EmailSendResult:
    ok: bool
    mode: str
    error: str | None = None
    provider: str | None = None


class EmailService:
    """Send email via SendGrid or SMTP with explicit delivery outcomes."""

    def __init__(self):
        self._recipients = _parse_recipients(settings.EMAIL_RECIPIENTS)
        self._from = settings.EMAIL_FROM
        self._provider = (settings.EMAIL_PROVIDER or "auto").strip().lower()
        self._api_key = settings.SENDGRID_API_KEY
        self._smtp_host = settings.SMTP_HOST
        self._smtp_port = settings.SMTP_PORT
        self._smtp_username = settings.SMTP_USERNAME
        self._smtp_password = settings.SMTP_PASSWORD
        self._smtp_use_tls = bool(settings.SMTP_USE_TLS)
        self._smtp_use_ssl = bool(settings.SMTP_USE_SSL)
        self._dry_run = settings.EMAIL_DRY_RUN

        self._client = None
        if self._api_key and not self._dry_run:
            import sendgrid  # type: ignore

            self._client = sendgrid.SendGridAPIClient(self._api_key)

    @staticmethod
    def _normalize_recipients(recipients: Iterable[str] | str | None) -> list[str]:
        if recipients is None:
            return []
        if isinstance(recipients, str):
            return _parse_recipients(recipients)
        return [x.strip() for x in recipients if str(x).strip()]

    def _effective_provider(self) -> str:
        if self._provider in {"sendgrid", "smtp", "none"}:
            return self._provider
        if self._api_key:
            return "sendgrid"
        if self._smtp_host:
            return "smtp"
        return "none"

    def _send_via_sendgrid(self, subject: str, html: str, to_list: list[str]) -> EmailSendResult:
        if not self._client:
            return EmailSendResult(ok=False, mode="failed", provider="sendgrid", error="sendgrid_not_configured")
        from sendgrid.helpers.mail import Mail, To  # type: ignore

        message = Mail(
            from_email=self._from,
            to_emails=[To(r) for r in to_list],
            subject=subject,
            html_content=html,
        )
        resp = self._client.send(message)
        if 200 <= int(resp.status_code) < 300:
            logger.info("email_sent", status=resp.status_code, provider="sendgrid", subject=subject, to=to_list)
            return EmailSendResult(ok=True, mode="sent", provider="sendgrid")
        err = f"sendgrid_http_{resp.status_code}"
        logger.error("email_send_failed", provider="sendgrid", status=resp.status_code, subject=subject, to=to_list)
        return EmailSendResult(ok=False, mode="failed", provider="sendgrid", error=err)

    def _send_via_smtp(self, subject: str, html: str, to_list: list[str]) -> EmailSendResult:
        if not self._smtp_host:
            return EmailSendResult(ok=False, mode="failed", provider="smtp", error="smtp_not_configured")

        message = EmailMessage()
        message["From"] = self._from
        message["To"] = ", ".join(to_list)
        message["Subject"] = subject
        message.set_content("HTML email attached.")
        message.add_alternative(html, subtype="html")

        if self._smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(self._smtp_host, int(self._smtp_port), context=context, timeout=30) as server:
                if self._smtp_username:
                    server.login(self._smtp_username, self._smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(self._smtp_host, int(self._smtp_port), timeout=30) as server:
                if self._smtp_use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if self._smtp_username:
                    server.login(self._smtp_username, self._smtp_password)
                server.send_message(message)

        logger.info("email_sent", provider="smtp", subject=subject, to=to_list)
        return EmailSendResult(ok=True, mode="sent", provider="smtp")

    def send_result(
        self,
        subject: str,
        html: str,
        recipients: Iterable[str] | str | None = None,
    ) -> EmailSendResult:
        to_list = self._normalize_recipients(recipients) if recipients is not None else self._recipients
        if not to_list:
            err = "email_no_recipients"
            logger.error(err, subject=subject)
            return EmailSendResult(ok=False, mode="failed", error=err, provider=None)

        if self._dry_run:
            logger.info("email_dry_run", subject=subject, to=to_list, preview=html[:300])
            return EmailSendResult(ok=True, mode="dry_run", provider="dry_run")

        provider = self._effective_provider()
        if provider == "sendgrid":
            try:
                return self._send_via_sendgrid(subject=subject, html=html, to_list=to_list)
            except Exception as exc:  # noqa: PERF203
                return EmailSendResult(ok=False, mode="failed", error=str(exc), provider="sendgrid")
        if provider == "smtp":
            try:
                return self._send_via_smtp(subject=subject, html=html, to_list=to_list)
            except Exception as exc:  # noqa: PERF203
                return EmailSendResult(ok=False, mode="failed", error=str(exc), provider="smtp")

        err = "email_provider_not_configured"
        logger.error(err, subject=subject, to=to_list)
        return EmailSendResult(ok=False, mode="failed", error=err, provider=None)

    def send(self, subject: str, html: str, recipients: Iterable[str] | str | None = None) -> EmailSendResult:
        result = self.send_result(subject=subject, html=html, recipients=recipients)
        if not result.ok:
            raise RuntimeError(result.error or "email_send_failed")
        return result
