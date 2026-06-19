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
