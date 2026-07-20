from datetime import datetime

import httpx

from app.main import app
from app.repositories.state_repository import get_state_repository


async def test_dashboard_uses_live_sales_review_data():
    """dashboard should surface real pending drafts instead of static admin filler."""
    draft_id = "DFT-DASHBOARD-LIVE"
    now = datetime.now().isoformat()
    get_state_repository().upsert_draft(
        {
            "draft_id": draft_id,
            "sender": "dashboard.customer@example.com",
            "subject": "Dashboard safety helmet quote",
            "body": "Can you quote 40 safety helmets?",
            "status": "pending",
            "created": now,
            "updated": now,
            "revisions": 0,
            "last_rejection_reason": "",
            "ai_draft_text": "Safety Helmet can be quoted for review.",
            "workflow": {
                "inquiry": {
                    "inquiry_type": "pricing",
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
            data={"username": "john", "password": "swift123", "next": "/dashboard"},
        )
        response = await client.get("/dashboard")

    assert response.status_code == 200
    assert "Dashboard safety helmet quote" in response.text
    assert "dashboard.customer@example.com" in response.text
    assert "Active Users" not in response.text
    assert "System Health" not in response.text
