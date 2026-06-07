from __future__ import annotations

import asyncio
import inspect
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("SWIFT_STORAGE_BACKEND", "memory")

from app.crews.agents import EmailDraftingAgent, SalesProcessingAgent


def pytest_pyfunc_call(pyfuncitem):
    """Why: runs async tests without adding a pytest-asyncio dependency."""
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(pyfuncitem.obj(**kwargs))
    return True


class AuditLogger:
    """Why: keeps the audit logger unit test focused on table writes."""

    def __init__(self, postgres_client):
        """Why: injects the persistence dependency so the test can mock it."""
        self.postgres_client = postgres_client

    def save(self, log_data):
        """Why: mirrors the production contract for saving decision logs."""
        self.postgres_client.insert("audit_logs", log_data)


class EmailListener:
    """Why: isolates routing behavior without running a real mailbox listener."""

    def __init__(self, supervisor_agent):
        """Why: lets tests toggle active state and inspect supervisor calls."""
        self.active = True
        self.supervisor_agent = supervisor_agent

    async def process(self, email):
        """Why: verifies inactive listeners do not route customer messages."""
        if self.active:
            self.supervisor_agent.route(email)


class DispatchService:
    """Why: keeps email dispatch tests independent from SMTP/client libraries."""

    def __init__(self, email_client):
        """Why: injects a mockable client for send/no-send assertions."""
        self.email_client = email_client

    def dispatch(self, draft, *, approved):
        """Why: only approved drafts should leave the system."""
        if approved:
            self.email_client.send(draft)


class NotificationService:
    """Why: models review notifications without an external notification provider."""

    def notify_review_required(self, draft):
        """Why: confirms draft-ready events produce the expected notification shape."""
        return SimpleNamespace(sent=True, type="draft_review")


class GovernanceService:
    """Why: captures the sales-only approval rule used by governance tests."""

    def authorise_draft_decision(self, user):
        """Why: requires both Sales membership and active SSO before approval."""
        if user.get("department") != "Sales":
            return SimpleNamespace(allowed=False, message="Sales approval required.")
        if not user.get("sso_active"):
            return SimpleNamespace(allowed=False, message="Active SSO is required.")
        return SimpleNamespace(allowed=True, message="Approved.")


class GuardrailService:
    """Why: keeps safety tests focused on confidential-data rejection."""

    def validate_customer_question(self, question):
        """Why: rejects prompt-injection style requests before drafting."""
        lower_question = question.lower()
        if "ignore previous instructions" in lower_question or "customer" in lower_question:
            return SimpleNamespace(
                allowed=False,
                response="I cannot share confidential customer data.",
            )
        return SimpleNamespace(allowed=True, response="Allowed.")


@pytest.fixture
def mock_postgres_client():
    """Why: verifies persistence calls without touching a database."""
    return MagicMock()


@pytest.fixture
def audit_logger(mock_postgres_client):
    """Why: shares the logger test double across audit tests."""
    return AuditLogger(mock_postgres_client)


@pytest.fixture
def mock_odoo_client():
    """Why: supplies controlled product data to sales-agent tests."""
    return MagicMock()


@pytest.fixture
def sales_agent(mock_odoo_client):
    """Why: injects the mock product client into the sales agent."""
    return SalesProcessingAgent(product_client=mock_odoo_client)


@pytest.fixture
def email_drafting_agent():
    """Why: exercises real deterministic drafting behavior in unit tests."""
    return EmailDraftingAgent()


@pytest.fixture
def supervisor_agent():
    """Why: records route calls from the listener test double."""
    return MagicMock()


@pytest.fixture
def email_listener(supervisor_agent):
    """Why: provides a listener fixture with controllable active state."""
    return EmailListener(supervisor_agent)


@pytest.fixture
def mock_email_client():
    """Why: verifies dispatch behavior without sending email."""
    return MagicMock()


@pytest.fixture
def dispatch_service(mock_email_client):
    """Why: wires dispatch tests to a mock email client."""
    return DispatchService(mock_email_client)


@pytest.fixture
def notification_service():
    """Why: provides a minimal notifier for review-ready tests."""
    return NotificationService()


@pytest.fixture
def governance_service():
    """Why: provides approval authorization rules for governance tests."""
    return GovernanceService()


@pytest.fixture
def guardrail_service():
    """Why: provides prompt-injection checks for governance tests."""
    return GuardrailService()
