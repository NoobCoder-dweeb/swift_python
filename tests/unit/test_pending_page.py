from datetime import datetime

import httpx

from app.main import app
from app.repositories.state_repository import get_state_repository


async def test_pending_page_shows_workflow_reviewable_draft_without_legacy_keywords():
    """structured workflow metadata should drive pending UI visibility."""
    draft_id = "DFT-PENDING-WORKFLOW"
    now = datetime.now().isoformat()
    get_state_repository().upsert_draft(
        {
            "draft_id": draft_id,
            "sender": "workflow.customer@example.com",
            "subject": "Safety helmet request",
            "body": "We need 40 safety helmets next week.",
            "status": "pending",
            "created": now,
            "updated": now,
            "revisions": 0,
            "last_rejection_reason": "",
            "ai_draft_text": "Safety Helmet can be prepared for review.",
            "workflow": {
                "inquiry": {
                    "inquiry_type": "mixed",
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
    assert draft_id in response.text
    assert "Safety helmet request" in response.text


async def test_pending_page_shows_product_references_inside_ai_draft():
    """product source links should be part of the response text under review."""
    draft_id = "DFT-PENDING-REFERENCES"
    now = datetime.now().isoformat()
    get_state_repository().upsert_draft(
        {
            "draft_id": draft_id,
            "sender": "reference.customer@example.com",
            "subject": "Safety helmet reference",
            "body": "We need 40 safety helmets next week.",
            "status": "pending",
            "created": now,
            "updated": now,
            "revisions": 0,
            "last_rejection_reason": "",
            "ai_draft_text": "Thank you for your inquiry.",
            "workflow": {
                "inquiry": {
                    "inquiry_type": "availability",
                },
                "product_context": {
                    "product": "Safety Helmet",
                    "sku": "SAFE-HELMET-001",
                    "source_url": "https://safetyware.com/product/safety-helmet/",
                    "price": 12.5,
                    "currency": "RM",
                    "stock_availability": 40,
                    "source": "postgres",
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
    assert "References:" in response.text
    assert "1. https://safetyware.com/product/safety-helmet/" in response.text
    assert "product-reference-card" not in response.text
    assert "draft-references" not in response.text


async def test_pending_page_marks_rejected_response_with_red_side_class():
    """rejected officer responses must not inherit the approved green side border."""
    repository = get_state_repository()
    now = datetime.now().isoformat()
    sender = "rejected.thread@example.com"
    subject = "Rejected response colour"
    repository.insert_audit(
        {
            "audit_id": "AUD-PENDING-REJECTED-COLOUR",
            "draft_id": "DFT-PENDING-REJECTED-PRIOR",
            "version_id": "DFT-PENDING-REJECTED-PRIOR-v1",
            "sender": sender,
            "subject": subject,
            "approver": "John Doe",
            "action": "rejected",
            "timestamp": now,
            "emailed_to": None,
            "sent": False,
            "customer_inquiry": "Please quote five units.",
            "ai_draft": "The rejected response.",
            "review_comment": "The facts need correction.",
        }
    )
    repository.upsert_draft(
        {
            "draft_id": "DFT-PENDING-REJECTED-CURRENT",
            "sender": sender,
            "subject": f"Re: {subject}",
            "body": "Please provide the corrected quote.",
            "status": "pending",
            "created": now,
            "updated": now,
            "revisions": 0,
            "last_rejection_reason": "",
            "ai_draft_text": "The regenerated response.",
            "workflow": {"inquiry": {"inquiry_type": "pricing"}},
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
    assert 'class="thread-item thread-item-officer is-rejected"' in response.text
    assert "Rejected response" in response.text
