import httpx

from app.core.config import get_app_settings, reset_app_settings
from app.crews.sales_inquiry_crew import run_sales_inquiry_workflow
from app.schemas.email import IncomingEmail


def test_zero_config_resolves_to_memory_storage(monkeypatch):
    """external integrators should not need PostgreSQL for first startup."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SWIFT_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("SWIFT_EXTERNAL_AGENT_URL", raising=False)
    monkeypatch.delenv("SWIFT_AGENT_BACKEND", raising=False)
    monkeypatch.delenv("SWIFT_CREWAI_ENABLED", raising=False)
    reset_app_settings()

    settings = get_app_settings()

    assert settings.storage_mode == "memory"
    assert settings.ui_enabled is True
    assert settings.resolved_agent_backend == "deterministic"
    assert settings.cors_origins == ["*"]

    reset_app_settings()


def test_external_agent_backend_accepts_valid_vendor_draft(monkeypatch):
    """vendor-hosted agents should plug in without changing workflow code."""
    monkeypatch.setenv("SWIFT_AGENT_BACKEND", "external")
    monkeypatch.setenv("SWIFT_EXTERNAL_AGENT_URL", "https://agents.example.test/draft")
    reset_app_settings()

    class Response:
        """minimal httpx response double for the external agent adapter."""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "provider": "vendor-agent",
                "ai_draft": (
                    "Hi,\n\n"
                    "Thanks for your inquiry about Product X. The approved reference "
                    "price is RM 120.00 per unit. Current available stock is "
                    "500 units.\n\n"
                    "Best regards,\n"
                    "Project Swift Support"
                ),
            }

    def fake_post(url, *, json, headers, timeout):
        assert url == "https://agents.example.test/draft"
        assert json["constraints"]["use_only_product_context"] is True
        assert json["product_context"]["stock_availability"] == 500
        assert timeout == 20.0
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)

    result = run_sales_inquiry_workflow(
        IncomingEmail(
            sender="buyer@example.com",
            subject="Product X quote and stock",
            body="Please quote 40 units of Product X and confirm stock.",
        )
    )

    assert result.execution_mode == "external"
    assert result.agent_models["provider"] == "vendor-agent"
    assert result.validation.valid is True
    assert "RM 120.00" in result.ai_draft
    assert "500 units" in result.ai_draft

    reset_app_settings()
