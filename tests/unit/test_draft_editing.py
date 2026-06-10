from fastapi.testclient import TestClient

from app.main import app
from data import add_generated_draft


def test_update_pending_draft_records_edited_audit():
    """Why: verifies inline edit saves and audit history capture."""
    client = TestClient(app)

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

    response = client.patch(f"/api/drafts/{draft.draft_id}", json={"ai_draft": new_text})
    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_id"] == draft.draft_id
    assert payload["ai_draft"] == new_text

    audits = client.get("/api/audits").json()
    assert any(
        item.get("draft_id") == draft.draft_id and item.get("action") == "edited"
        for item in audits
    )
