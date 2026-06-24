import pytest

from app.core.config import AppSettings
from app.services import email_dispatcher
from app.services.email_dispatcher import send_approved_draft


def test_email_sent_after_approval(dispatch_service, mock_email_client):
    """ensures only approved drafts are sent to customers."""
    draft = {"to": "customer@example.com", "content": "Dear customer..."}

    dispatch_service.dispatch(draft, approved=True)

    mock_email_client.send.assert_called_once()


def test_email_not_sent_when_rejected(dispatch_service, mock_email_client):
    """prevents rejected drafts from leaving the review workflow."""
    draft = {"to": "customer@example.com", "content": "Dear customer..."}

    dispatch_service.dispatch(draft, approved=False)

    mock_email_client.send.assert_not_called()


def test_approved_email_sets_reply_to_for_cloudmailin(monkeypatch):
    """customer Gmail replies should route to CloudMailin when configured."""
    sent_messages = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def starttls(self):
            return None

        def login(self, username, password):
            return None

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(email_dispatcher.smtplib, "SMTP", FakeSMTP)

    settings = AppSettings(
        storage_backend="memory",
        database_url="",
        ui_enabled=True,
        seed_demo_data=False,
        cors_origins=["*"],
        agent_backend="deterministic",
        external_agent_url="",
        external_agent_api_key="",
        external_agent_timeout=20.0,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="sender@example.com",
        smtp_password="password",
        smtp_from_email="sender@example.com",
        smtp_reply_to_email="reply-target@cloudmailin.net",
        smtp_from_name="Project Swift Support",
        smtp_use_tls=True,
        smtp_timeout=20.0,
        cloudmailin_basic_username="user",
        cloudmailin_basic_password="password",
        session_secret_key="test-session-secret",
    )

    result = send_approved_draft(
        recipient="customer@example.com",
        subject="Stock availability request",
        body="Approved response",
        settings=settings,
    )

    assert result.sent is True
    assert sent_messages[0]["Reply-To"] == "reply-target@cloudmailin.net"
    assert sent_messages[0]["Subject"] == "Re: Stock availability request"


def test_approved_email_requires_reply_to_for_cloudmailin():
    """approval should not send replies that would route back to Gmail only."""
    settings = AppSettings(
        storage_backend="memory",
        database_url="",
        ui_enabled=True,
        seed_demo_data=False,
        cors_origins=["*"],
        agent_backend="deterministic",
        external_agent_url="",
        external_agent_api_key="",
        external_agent_timeout=20.0,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="sender@example.com",
        smtp_password="password",
        smtp_from_email="sender@example.com",
        smtp_reply_to_email="",
        smtp_from_name="Project Swift Support",
        smtp_use_tls=True,
        smtp_timeout=20.0,
        cloudmailin_basic_username="user",
        cloudmailin_basic_password="password",
        session_secret_key="test-session-secret",
    )

    result = send_approved_draft(
        recipient="customer@example.com",
        subject="Stock availability request",
        body="Approved response",
        settings=settings,
    )

    assert result.sent is False
    assert result.error == "missing_reply_to"
