import httpx

from app.core.config import reset_app_settings
from app.main import app
from app.services.draft_service import DraftService
from data import add_generated_draft


async def test_update_pending_draft_records_edited_audit():
    """verifies inline edit saves and audit history capture."""
    draft = add_generated_draft(
        {
            "from": "edit.user@example.com",
            "subject": "Quick stock check",
            "body": "Can you confirm if product X is available for immediate shipment?",
        },
        ai_draft="Initial AI draft response.",
        status="pending",
    )

    assert draft is not None
    new_text = "Updated AI draft response with a minor clarification."

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.patch(
            f"/api/drafts/{draft.draft_id}",
            json={"ai_draft": new_text},
        )
        audits = (await client.get("/api/audits/")).json()

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_id"] == draft.draft_id
    assert payload["ai_draft"] == new_text

    assert any(
        item.get("draft_id") == draft.draft_id and item.get("action") == "edited"
        for item in audits
    )


async def test_reject_regenerates_from_stored_data_with_reviewer_feedback():
    """reject comments must rerun the supervised workflow, not fake a revision."""
    draft = add_generated_draft(
        {
            "from": "feedback.user@example.com",
            "subject": "Product X price",
            "body": "Can I get pricing for 40 units of Product X?",
        },
        ai_draft="Old draft that omitted approved stock availability.",
        status="pending",
        draft_id="DFT-FEEDBACK-REJECT",
    )

    assert draft is not None

    result = DraftService().reject_draft(
        draft.draft_id,
        reason="Please make it brief and include stock availability.",
    )

    assert result["success"] is True
    regenerated = result["draft"]
    assert regenerated["draft_id"] == draft.draft_id
    assert regenerated["last_rejection_reason"] == (
        "Please make it brief and include stock availability."
    )
    assert regenerated["revisions"] == 1
    assert "500 units" in regenerated["ai_draft"]
    assert "USD 120.00" in regenerated["ai_draft"]
    assert "Old draft" not in regenerated["ai_draft"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        audits = (await client.get("/api/audits/")).json()

    audit = next(
        item
        for item in audits
        if item.get("draft_id") == draft.draft_id and item.get("action") == "rejected"
    )
    assert audit["review_comment"] == "Please make it brief and include stock availability."
    assert audit["details"]["product_context"]["stock_availability"] == 500
    assert any("Reviewer feedback applied" in note for note in audit["details"]["learning_notes"])


async def test_approval_sends_response_to_original_gmail_sender(monkeypatch):
    """approval should address the response to the customer who sent the email."""
    sent_messages = []

    class FakeSMTP:
        """captures outbound SMTP messages without sending network traffic."""

        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.started_tls = False
            self.login_args = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def starttls(self):
            self.started_tls = True

        def login(self, username, password):
            self.login_args = (username, password)

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setenv("SWIFT_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SWIFT_SMTP_PORT", "587")
    monkeypatch.setenv("SWIFT_SMTP_USERNAME", "sales@example.com")
    monkeypatch.setenv("SWIFT_SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("SWIFT_SMTP_FROM_EMAIL", "sales@example.com")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    reset_app_settings()

    draft = add_generated_draft(
        {
            "from": "shaukoay.dev@gmail.com",
            "subject": "Product X pricing for Gmail approval test",
            "body": "Can I get pricing for 40 units of Product X?",
        },
        ai_draft="Hi,\n\nProduct X is USD 120.00 per unit.\n\nBest regards,\nProject Swift Support",
        status="pending",
    )

    assert draft is not None

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(f"/api/drafts/{draft.draft_id}/approve")
    finally:
        reset_app_settings()

    assert response.status_code == 200
    payload = response.json()
    audit = payload["audit"]
    assert payload["success"] is True
    assert audit["sent"] is True
    assert audit["sender"] == "shaukoay.dev@gmail.com"
    assert audit["emailed_to"] == "shaukoay.dev@gmail.com"
    assert "sent it to shaukoay.dev@gmail.com" in audit["content"]
    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == "shaukoay.dev@gmail.com"
    assert sent_messages[0].get_content().strip() == draft.ai_draft
