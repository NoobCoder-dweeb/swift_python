import httpx

from app.core.config import reset_app_settings
from app.main import app
from app.repositories.state_repository import get_state_repository
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
        await client.post(
            "/login",
            data={"username": "john", "password": "swift123", "next": "/pending"},
        )
        response = await client.patch(
            f"/api/drafts/{draft.draft_id}",
            json={"ai_draft": new_text},
        )
        audits = (await client.get("/api/audits/")).json()

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_id"] == draft.draft_id
    assert payload["ai_draft"] == new_text

    audit = next(
        item
        for item in audits
        if item.get("draft_id") == draft.draft_id and item.get("action") == "edited"
    )
    assert audit["approver"] == "John Doe"


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
        approver="Aisha Sales",
    )

    assert result["success"] is True
    regenerated = result["draft"]
    assert regenerated["draft_id"] == draft.draft_id
    assert regenerated["last_rejection_reason"] == (
        "Please make it brief and include stock availability."
    )
    assert regenerated["revisions"] == 1
    assert "500 units" in regenerated["ai_draft"]
    assert "RM 120.00" in regenerated["ai_draft"]
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
    assert audit["approver"] == "Aisha Sales"
    assert audit["details"]["product_context"]["stock_availability"] == 500
    assert any("Reviewer feedback applied" in note for note in audit["details"]["learning_notes"])


async def test_reject_regenerates_follow_up_with_thread_context_quantity(monkeypatch):
    """regeneration should preserve product context and use the current reply quantity."""
    monkeypatch.setenv("SWIFT_AGENT_BACKEND", "deterministic")
    monkeypatch.setenv("SWIFT_STORAGE_BACKEND", "memory")
    reset_app_settings()
    repository = get_state_repository()
    sender = "followup.price@example.com"
    subject = "Inquiry for safety order"
    repository.insert_audit(
        {
            "audit_id": "AUD-FOLLOWUP-PRICE-CONTEXT",
            "draft_id": "DFT-FOLLOWUP-PRICE-PRIOR",
            "version_id": "DFT-FOLLOWUP-PRICE-PRIOR-v1",
            "sender": sender,
            "subject": subject,
            "approver": "Aisha Sales",
            "action": "approved",
            "timestamp": "2026-06-23T08:00:00",
            "emailed_to": sender,
            "sent": True,
            "customer_inquiry": "Can you confirm Product X stock?",
            "ai_draft": (
                "Hi,\n\n"
                "Thanks for your inquiry about Product X. The approved reference "
                "price is RM 120.00 per unit. Current available stock is 500 units.\n\n"
                "Best regards,\n"
                "Project Swift Support"
            ),
        }
    )
    draft = add_generated_draft(
        {
            "from": sender,
            "subject": f"Re: {subject}",
            "body": "How much total if I want 20 units?",
        },
        ai_draft=(
            "Hi,\n\n"
            "Thanks for your inquiry about Product X.\n"
            "The total price for 500 units is RM 60000.00.\n\n"
            "Best regards,\n"
            "Project Swift Support"
        ),
        status="pending",
        workflow={
            "inquiry": {"inquiry_type": "pricing"},
            "product_context": {
                "product": "Product X",
                "sku": "PROD-X-001",
                "source_url": "https://safetyware.com/product/product-x/",
                "price": 120.0,
                "currency": "RM",
                "stock_availability": 500,
                "source": "local_catalog",
            },
        },
        draft_id="DFT-FOLLOWUP-PRICE-REJECT",
    )

    assert draft is not None

    result = DraftService().reject_draft(
        draft.draft_id,
        reason="The regenerated response should answer the customer's latest reply.",
        approver="Aisha Sales",
    )

    assert result["success"] is True
    assert result["status"] == "pending"
    regenerated = result["draft"]
    assert get_state_repository().get_draft(draft.draft_id) is not None
    assert "Product X" in regenerated["ai_draft"]
    assert "total price for 20 units is RM 2400.00" in regenerated["ai_draft"]
    assert "20 x RM 120.00 = RM 2400.00" in regenerated["ai_draft"]
    assert "500 units" not in regenerated["ai_draft"]
    assert "only supports product pricing" not in regenerated["ai_draft"]


async def test_reject_cleans_nested_thread_context_from_customer_body(monkeypatch):
    """internal workflow context must not be persisted as customer email text."""
    monkeypatch.setenv("SWIFT_AGENT_BACKEND", "deterministic")
    monkeypatch.setenv("SWIFT_STORAGE_BACKEND", "memory")
    reset_app_settings()
    repository = get_state_repository()
    polluted_body = (
        "Current customer reply to answer now: Current customer reply to answer now: "
        "How much total if I want 20 units?\n"
        "Use this only to infer omitted product, quantity, pricing, availability, "
        "and delivery context.\n"
        "Customer Customer email: I would like to inquire about Product X.\n"
        "The approved reference price is RM 120.00 per unit.\n"
        "Current available stock is 500 units."
    )
    draft = add_generated_draft(
        {
            "from": "polluted.followup@example.com",
            "subject": "Re: Product X inquiry",
            "body": polluted_body,
        },
        ai_draft="Wrong draft using the old context quantity.",
        status="pending",
        workflow={
            "inquiry": {"inquiry_type": "pricing"},
            "product_context": {
                "product": "Product X",
                "sku": "PROD-X-001",
                "source_url": "https://safetyware.com/product/product-x/",
                "price": 120.0,
                "currency": "RM",
                "stock_availability": 500,
                "source": "local_catalog",
            },
        },
        draft_id="DFT-POLLUTED-FOLLOWUP",
    )

    assert draft is not None

    result = DraftService().reject_draft(
        draft.draft_id,
        reason="Still wrong, please answer the latest customer reply.",
        approver="Aisha Sales",
    )

    assert result["success"] is True
    regenerated = result["draft"]
    stored = repository.get_draft(draft.draft_id)
    assert stored is not None
    assert regenerated["customer_inquiry"] == "How much total if I want 20 units?"
    assert stored["body"] == "How much total if I want 20 units?"
    assert "Current customer reply to answer now" not in regenerated["customer_inquiry"]
    assert "Use this only to infer" not in regenerated["customer_inquiry"]
    assert "total price for 20 units is RM 2400.00" in regenerated["ai_draft"]
    assert "500 units" not in regenerated["ai_draft"]


async def test_reject_feedback_quantity_uses_corrected_latest_quantity(monkeypatch):
    """feedback that names the wrong and right quantities should use the correction."""
    monkeypatch.setenv("SWIFT_AGENT_BACKEND", "deterministic")
    monkeypatch.setenv("SWIFT_STORAGE_BACKEND", "memory")
    reset_app_settings()
    repository = get_state_repository()
    sender = "feedback.quantity@example.com"
    subject = "Inquiry for Product X"
    repository.insert_audit(
        {
            "audit_id": "AUD-FEEDBACK-QUANTITY-CONTEXT",
            "draft_id": "DFT-FEEDBACK-QUANTITY-PRIOR",
            "version_id": "DFT-FEEDBACK-QUANTITY-PRIOR-v1",
            "sender": sender,
            "subject": subject,
            "approver": "Aisha Sales",
            "action": "approved",
            "timestamp": "2026-06-23T08:00:00",
            "emailed_to": sender,
            "sent": True,
            "customer_inquiry": "I would like to inquire about Product X.",
            "ai_draft": (
                "Hi,\n\n"
                "The approved reference price is RM 120.00 per unit. "
                "Current available stock is 74 units.\n\n"
                "Best regards,\n"
                "Project Swift Support"
            ),
        }
    )
    draft = add_generated_draft(
        {
            "from": sender,
            "subject": f"Re: {subject}",
            "body": "inventory?",
        },
        ai_draft=(
            "Hi,\n\n"
            "The total price for 74 units is RM 8880.00.\n\n"
            "Best regards,\n"
            "Project Swift Support"
        ),
        status="pending",
        workflow={
            "inquiry": {"inquiry_type": "availability"},
            "product_context": {
                "product": "Product X",
                "sku": "PROD-X-001",
                "price": 120.0,
                "currency": "RM",
                "stock_availability": 74,
                "source": "local_catalog",
            },
        },
        draft_id="DFT-FEEDBACK-QUANTITY",
    )

    assert draft is not None

    result = DraftService().reject_draft(
        draft.draft_id,
        reason=(
            "Still wrong, it computes 74 units. I WANT TO Compute the total "
            "price of 20 units"
        ),
        approver="Aisha Sales",
    )

    assert result["success"] is True
    regenerated = result["draft"]
    assert "total price for 20 units is RM 2400.00" in regenerated["ai_draft"]
    assert "20 x RM 120.00 = RM 2400.00" in regenerated["ai_draft"]
    assert "total price for 74 units" not in regenerated["ai_draft"]
    assert regenerated["customer_inquiry"] == "inventory?"


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
    monkeypatch.setenv("SWIFT_SMTP_REPLY_TO_EMAIL", "inbound@cloudmailin.net")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    reset_app_settings()

    draft = add_generated_draft(
        {
            "from": "shaukoay.dev@gmail.com",
            "subject": "Product X pricing for Gmail approval test",
            "body": "Can I get pricing for 40 units of Product X?",
        },
        ai_draft="Hi,\n\nProduct X is RM 120.00 per unit.\n\nBest regards,\nProject Swift Support",
        status="pending",
        workflow={
            "inquiry": {"inquiry_type": "pricing"},
            "product_context": {
                "product": "Product X",
                "sku": "PROD-X-001",
                "source_url": "https://safetyware.com/product/product-x/",
                "price": 120.0,
                "currency": "RM",
                "stock_availability": 500,
                "source": "local_catalog",
            },
        },
    )

    assert draft is not None

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            await client.post(
                "/login",
                data={"username": "mira", "password": "swift123", "next": "/pending"},
            )
            response = await client.post(f"/api/drafts/{draft.draft_id}/approve")
    finally:
        reset_app_settings()

    assert response.status_code == 200
    payload = response.json()
    audit = payload["audit"]
    assert payload["success"] is True
    assert audit["sent"] is True
    assert audit["sender"] == "shaukoay.dev@gmail.com"
    assert audit["approver"] == "Mira Tan"
    assert audit["emailed_to"] == "shaukoay.dev@gmail.com"
    assert "sent it to shaukoay.dev@gmail.com" in audit["content"]
    assert len(sent_messages) == 1
    assert sent_messages[0]["To"] == "shaukoay.dev@gmail.com"
    assert sent_messages[0]["Reply-To"] == "inbound@cloudmailin.net"
    assert sent_messages[0].get_content().strip() == draft.ai_draft
    assert "References:" in sent_messages[0].get_content()
    assert "1. https://safetyware.com/product/product-x/" in sent_messages[0].get_content()


async def test_approval_succeeds_without_smtp_and_records_manual_send(monkeypatch):
    """local Docker approval should not fail just because SMTP is unset."""
    for name in (
        "SWIFT_SMTP_HOST",
        "SWIFT_SMTP_USERNAME",
        "SWIFT_SMTP_PASSWORD",
        "SWIFT_SMTP_FROM_EMAIL",
        "SWIFT_SMTP_REPLY_TO_EMAIL",
    ):
        monkeypatch.setenv(name, "")
    reset_app_settings()

    draft = add_generated_draft(
        {
            "from": "local.customer@example.com",
            "subject": "Product X pricing approval without SMTP",
            "body": "Can I get pricing for 40 units of Product X?",
        },
        ai_draft="Hi,\n\nProduct X is RM 120.00 per unit.\n\nBest regards,\nProject Swift Support",
        status="pending",
    )

    assert draft is not None

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            await client.post(
                "/login",
                data={"username": "john", "password": "swift123", "next": "/pending"},
            )
            response = await client.post(f"/api/drafts/{draft.draft_id}/approve")
    finally:
        reset_app_settings()

    assert response.status_code == 200
    payload = response.json()
    audit = payload["audit"]
    assert payload["success"] is True
    assert payload["status"] == "approved"
    assert "SMTP is not configured" in payload["message"]
    assert audit["action"] == "approved"
    assert audit["approver"] == "John Doe"
    assert audit["sent"] is False
    assert audit["dispatch_error"] == "smtp_not_configured"
    assert audit["details"]["requires_manual_send"] is True
    assert get_state_repository().get_draft(draft.draft_id) is None
