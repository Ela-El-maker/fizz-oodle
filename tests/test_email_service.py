from __future__ import annotations

import pytest

from apps.core import email_service


def test_email_service_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "EMAIL_RECIPIENTS", "ops@example.com")
    monkeypatch.setattr(email_service.settings, "EMAIL_DRY_RUN", True)
    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "auto")

    svc = email_service.EmailService()
    result = svc.send_result(subject="Test", html="<p>hello</p>")

    assert result.ok is True
    assert result.mode == "dry_run"
    assert result.provider == "dry_run"


def test_email_service_no_recipients_is_failure(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "EMAIL_RECIPIENTS", "")
    monkeypatch.setattr(email_service.settings, "EMAIL_DRY_RUN", False)
    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "none")

    svc = email_service.EmailService()
    result = svc.send_result(subject="Test", html="<p>hello</p>")

    assert result.ok is False
    assert result.error == "email_no_recipients"


def test_email_service_unconfigured_provider_is_failure(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "EMAIL_RECIPIENTS", "ops@example.com")
    monkeypatch.setattr(email_service.settings, "EMAIL_DRY_RUN", False)
    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "none")
    monkeypatch.setattr(email_service.settings, "SENDGRID_API_KEY", "")
    monkeypatch.setattr(email_service.settings, "SMTP_HOST", "")

    svc = email_service.EmailService()
    result = svc.send_result(subject="Test", html="<p>hello</p>")

    assert result.ok is False
    assert result.error == "email_provider_not_configured"
    with pytest.raises(RuntimeError):
        svc.send(subject="Test", html="<p>hello</p>")


def test_email_service_smtp_send_success(monkeypatch) -> None:
    sent_messages: list[object] = []

    class _FakeSMTP:
        def __init__(self, host, port, timeout=30):
            assert host == "smtp.example.com"
            assert int(port) == 587
            assert timeout == 30

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, username, password):
            assert username == "user"
            assert password == "pass"

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(email_service.settings, "EMAIL_RECIPIENTS", "ops@example.com")
    monkeypatch.setattr(email_service.settings, "EMAIL_DRY_RUN", False)
    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(email_service.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(email_service.settings, "SMTP_USERNAME", "user")
    monkeypatch.setattr(email_service.settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(email_service.settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(email_service.settings, "SMTP_USE_SSL", False)
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)

    svc = email_service.EmailService()
    result = svc.send_result(subject="SMTP Test", html="<p>hello</p>")

    assert result.ok is True
    assert result.provider == "smtp"
    assert len(sent_messages) == 1
