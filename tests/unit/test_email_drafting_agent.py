import pytest


def test_email_draft_uses_only_odoo_data(email_drafting_agent):
    """ensures drafts stay grounded in approved product context."""
    info = {"product": "Helmet", "stock_availability": 5}

    draft = email_drafting_agent.generate(info)

    assert "Helmet" in draft
    assert "5" in draft
    assert "unknown" not in draft.lower()


def test_invalid_draft_format_triggers_regeneration(email_drafting_agent):
    """protects review quality by rejecting under-specified drafts."""
    info = {"product": "Helmet", "stock_availability": 5}

    result = email_drafting_agent.validate_draft("helmet 5", info)

    assert result.valid is False
    assert result.action == "regenerate"
