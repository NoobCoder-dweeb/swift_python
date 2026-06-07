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
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(pyfuncitem.obj(**kwargs))
    return True


class AuditLogger:
    def __init__(self, postgres_client):
        self.postgres_client = postgres_client

    def save(self, log_data):
        self.postgres_client.insert("audit_logs", log_data)


class EmailListener:
    def __init__(self, supervisor_agent):
        self.active = True
        self.supervisor_agent = supervisor_agent

    async def process(self, email):
        if self.active:
            self.supervisor_agent.route(email)


class DispatchService:
    def __init__(self, email_client):
        self.email_client = email_client

    def dispatch(self, draft, *, approved):
        if approved:
            self.email_client.send(draft)


class NotificationService:
    def notify_review_required(self, draft):
        return SimpleNamespace(sent=True, type="draft_review")


class GovernanceService:
    def authorise_draft_decision(self, user):
        if user.get("department") != "Sales":
            return SimpleNamespace(allowed=False, message="Sales approval required.")
        if not user.get("sso_active"):
            return SimpleNamespace(allowed=False, message="Active SSO is required.")
        return SimpleNamespace(allowed=True, message="Approved.")


class GuardrailService:
    def validate_customer_question(self, question):
        lower_question = question.lower()
        if "ignore previous instructions" in lower_question or "customer" in lower_question:
            return SimpleNamespace(
                allowed=False,
                response="I cannot share confidential customer data.",
            )
        return SimpleNamespace(allowed=True, response="Allowed.")


@pytest.fixture
def mock_postgres_client():
    return MagicMock()


@pytest.fixture
def audit_logger(mock_postgres_client):
    return AuditLogger(mock_postgres_client)


@pytest.fixture
def mock_odoo_client():
    return MagicMock()


@pytest.fixture
def sales_agent(mock_odoo_client):
    return SalesProcessingAgent(product_client=mock_odoo_client)


@pytest.fixture
def email_drafting_agent():
    return EmailDraftingAgent()


@pytest.fixture
def supervisor_agent():
    return MagicMock()


@pytest.fixture
def email_listener(supervisor_agent):
    return EmailListener(supervisor_agent)


@pytest.fixture
def mock_email_client():
    return MagicMock()


@pytest.fixture
def dispatch_service(mock_email_client):
    return DispatchService(mock_email_client)


@pytest.fixture
def notification_service():
    return NotificationService()


@pytest.fixture
def governance_service():
    return GovernanceService()


@pytest.fixture
def guardrail_service():
    return GuardrailService()
