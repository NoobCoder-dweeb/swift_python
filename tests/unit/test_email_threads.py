from datetime import datetime

import httpx

from app.main import app
from app.schemas.draft import EmailPayload
from app.repositories.state_repository import get_state_repository
from app.services.draft_service import DraftService
from data import add_generated_draft, get_drafts


def test_follow_up_draft_includes_prior_approved_thread_response():
    """customer replies should carry prior officer responses into review."""
    repository = get_state_repository()
    sender = "thread.customer@example.com"
    subject = "Thread safety helmet availability"
    timestamp = datetime.now().isoformat()
    repository.insert_audit(
        {
            "audit_id": "AUD-THREAD-PRIOR",
            "draft_id": "DFT-THREAD-PRIOR",
            "version_id": "DFT-THREAD-PRIOR-v1",
            "sender": sender,
            "subject": subject,
            "approver": "Aisha Sales",
            "action": "approved",
            "timestamp": timestamp,
            "emailed_to": sender,
            "sent": True,
            "customer_inquiry": "Can you confirm helmet stock?",
            "ai_draft": "We have 40 helmets available for next week.",
        }
    )

    draft = add_generated_draft(
        {
            "from": sender,
            "subject": f"Re: {subject}",
            "body": "Can you also confirm stock for 80 helmets?",
        },
        ai_draft="We can check allocation for 80 helmets.",
        workflow={
            "inquiry": {"inquiry_type": "availability"},
            "product_context": {
                "product": "Safety Helmet",
                "sku": "SAFE-HELMET-001",
                "source_url": "https://safetyware.com/product/safety-helmet/",
                "price": 25.0,
                "currency": "RM",
                "stock_availability": 120,
                "source": "local_catalog",
            },
        },
        draft_id="DFT-THREAD-FOLLOWUP",
    )

    assert draft is not None
    stored = next(item for item in get_drafts() if item.draft_id == draft.draft_id)
    payload = stored.to_dict()

    assert payload["thread_count"] == 3
    assert [item["kind"] for item in payload["thread_history"]] == [
        "customer",
        "officer",
        "customer",
    ]
    assert payload["thread_history"][0]["body"] == "Can you confirm helmet stock?"
    assert payload["thread_history"][1]["body"] == (
        "We have 40 helmets available for next week."
    )
    assert payload["thread_history"][1]["meta"] == "Aisha Sales"
    assert payload["thread_history"][1]["sender"] == "Aisha Sales"
    assert payload["thread_history"][2]["body"] == (
        "Can you also confirm stock for 80 helmets?"
    )
    assert payload["thread_history"][2]["is_current"] is True
    assert payload["product_reference"]["product"] == "Safety Helmet"
    assert payload["product_reference"]["url"] == "https://safetyware.com/product/safety-helmet/"


def test_initiation_draft_does_not_create_email_thread():
    """first customer emails should use the Customer Email section, not a thread."""
    draft = add_generated_draft(
        {
            "from": "thread.new.customer@example.com",
            "subject": "New safety helmet pricing",
            "body": "Can you quote pricing for 20 safety helmets?",
        },
        ai_draft="The approved reference price is RM 25.00 per unit.",
        workflow={
            "inquiry": {"inquiry_type": "pricing"},
            "product_context": {
                "product": "Safety Helmet",
                "sku": "SAFE-HELMET-001",
                "price": 25.0,
                "currency": "RM",
                "stock_availability": 120,
                "source": "local_catalog",
            },
        },
        draft_id="DFT-THREAD-INITIATION",
    )

    assert draft is not None
    payload = draft.to_dict()

    assert payload["thread_count"] == 0
    assert payload["thread_history"] == []


async def test_pending_page_renders_email_thread_panel():
    """sales officers should see prior responses on the review card."""
    repository = get_state_repository()
    sender = "thread.page.customer@example.com"
    subject = "Thread page stock request"
    now = datetime.now().isoformat()
    repository.insert_audit(
        {
            "audit_id": "AUD-THREAD-PAGE",
            "draft_id": "DFT-THREAD-PAGE-PRIOR",
            "version_id": "DFT-THREAD-PAGE-PRIOR-v1",
            "sender": sender,
            "subject": subject,
            "approver": "John Doe",
            "action": "approved",
            "timestamp": now,
            "emailed_to": sender,
            "sent": True,
            "customer_inquiry": "Is this available?",
            "ai_draft": "The original approved response is visible here.",
        }
    )
    repository.upsert_draft(
        {
            "draft_id": "DFT-THREAD-PAGE-FOLLOWUP",
            "sender": sender,
            "subject": f"Re: {subject}",
            "body": "Can I increase the quantity to 120 units?",
            "status": "pending",
            "created": now,
            "updated": now,
            "revisions": 0,
            "last_rejection_reason": "",
            "ai_draft_text": "We can review availability for 120 units.",
            "workflow": {
                "inquiry": {"inquiry_type": "availability"},
                "product_context": {
                    "product": "Safety Helmet",
                    "sku": "SAFE-HELMET-001",
                    "source_url": "https://safetyware.com/product/safety-helmet/",
                    "price": 25.0,
                    "currency": "RM",
                    "stock_availability": 120,
                    "source": "local_catalog",
                },
            },
        }
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        await client.post(
            "/login",
            data={"username": "john", "password": "swift123", "next": "/pending"},
        )
        response = await client.get("/pending")

    assert response.status_code == 200
    assert "Email Thread" in response.text
    assert "3 conversation messages" in response.text
    assert "John Doe" in response.text
    assert "Is this available?" in response.text
    assert "The original approved response is visible here." in response.text
    assert "Can I increase the quantity to 120 units?" in response.text
    assert "References:" in response.text
    assert "1. https://safetyware.com/product/safety-helmet/" in response.text
    assert "Product Reference" not in response.text
    assert "View product" not in response.text


async def test_thread_context_lets_ai_resolve_omitted_product_in_follow_up():
    """new replies can omit the product when the prior thread named it."""
    current_reply = "I would like to have 20 units and delivery by courier."
    draft = await DraftService().generate_draft(
        EmailPayload(
            sender="thread.ai.customer@example.com",
            subject="Re: Product X availability",
            body=current_reply,
            conversation_context=(
                "Conversation history for resolving references in the current customer reply.\n"
                "Customer Customer email: Do you have Product X in stock?\n"
                "Company Approved response: Current available stock is 500 units."
            ),
        )
    )

    assert draft.status == "pending"
    assert draft.customer_inquiry == current_reply
    assert "Product X" in draft.ai_draft
    assert "20 units" in draft.ai_draft


async def test_thread_context_does_not_overanswer_pricing_only_follow_up():
    """pricing-only follow-ups should not volunteer stock or delivery prompts."""
    current_reply = "Hi, would like to get pricing for 20 units."
    draft = await DraftService().generate_draft(
        EmailPayload(
            sender="thread.price.customer@example.com",
            subject="Re: Fire extinguisher inquiry",
            body=current_reply,
            conversation_context=(
                "Conversation history for resolving references in the current customer reply.\n"
                "Customer Customer email: Do you have Product X in stock?\n"
                "Company Approved response: Current available stock is 478 units."
            ),
        )
    )

    assert draft.status == "pending"
    assert "Product X" in draft.ai_draft
    assert "total price for 20 units is RM 2400.00" in draft.ai_draft
    assert "20 x RM 120.00 = RM 2400.00" in draft.ai_draft
    assert "RM 120.00" in draft.ai_draft
    assert "Current available stock" not in draft.ai_draft
    assert "within the current available stock" not in draft.ai_draft
    assert "requested delivery" not in draft.ai_draft


async def test_listing_follow_up_quotes_selected_product(monkeypatch):
    """a customer selecting one listed product should not receive the list again."""
    class BookletsProductClient:
        def get_product(self, query):
            assert "Booklets" in query
            return {
                "product": "Booklets",
                "sku": "SW-BUSINESS-AND-EVENT-MATER-12619-451",
                "price": 96.11,
                "currency": "RM",
                "stock_availability": 101,
                "source": "postgres",
                "confidence": 0.96,
                "notes": ["Category: Business And Event Materials"],
            }

    monkeypatch.setattr(
        "app.crews.sales_inquiry_crew.build_product_lookup_client",
        lambda: BookletsProductClient(),
    )

    current_reply = "I would like for you to quote Booklets"
    draft = await DraftService().generate_draft(
        EmailPayload(
            sender="thread.listing.customer@example.com",
            subject="Re: Inquiry of products",
            body=current_reply,
            conversation_context=(
                "Conversation history for resolving references in the current customer reply.\n"
                "Customer Customer email: Could you list some products that are top 3?\n"
                "Company Approved response: The following approved products match your request:\n"
                "- Booklets (SW-BUSINESS-AND-EVENT-MATER-12619-451): RM 96.11 per unit, 101 unit available.\n"
                "- Brochures (SW-BUSINESS-AND-EVENT-MATER-12620-799): RM 109.03 per unit, 143 unit available.\n"
                "- Business Cards (SW-BUSINESS-AND-EVENT-MATER-12606-489): RM 85.01 per unit, 198 unit available."
            ),
        )
    )

    assert draft.status == "pending"
    assert draft.customer_inquiry == current_reply
    assert "Booklets" in draft.ai_draft
    assert "approved reference price is RM 96.11 per unit" in draft.ai_draft
    assert "Please confirm the missing details: quantity" in draft.ai_draft
    assert "The following approved products match your request" not in draft.ai_draft
    assert "Brochures" not in draft.ai_draft
    assert "Business Cards" not in draft.ai_draft
    assert "12620 units" not in draft.ai_draft
