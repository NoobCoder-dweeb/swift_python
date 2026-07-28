import httpx

from app.core.config import reset_app_settings
from app.main import app
from app.repositories.state_repository import get_state_repository


async def test_email_ingestion_to_review_approval_records_audit(monkeypatch):
    """customer email intake should flow through review approval and audit logging."""
    monkeypatch.setenv("SWIFT_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("SWIFT_AGENT_BACKEND", "deterministic")
    for name in (
        "SWIFT_SMTP_HOST",
        "SWIFT_SMTP_USERNAME",
        "SWIFT_SMTP_PASSWORD",
        "SWIFT_SMTP_FROM_EMAIL",
        "SWIFT_SMTP_REPLY_TO_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_app_settings()

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            ingest_response = await client.post(
                "/api/emails/ingest",
                json={
                    "from": "integration.customer@example.com",
                    "subject": "Integration helmet pricing request",
                    "body": "Can I get pricing for 40 units of Product X?",
                },
            )

            assert ingest_response.status_code == 200
            ingest_payload = ingest_response.json()
            assert ingest_payload["success"] is True
            assert ingest_payload["ingested"] is True
            draft_id = ingest_payload["draft"]["draft_id"]

            queue_response = await client.get("/api/drafts/")
            assert queue_response.status_code == 200
            assert any(item["draft_id"] == draft_id for item in queue_response.json())

            login_response = await client.post(
                "/login",
                data={"username": "john", "password": "swift123", "next": "/pending"},
            )
            assert login_response.status_code == 303

            pending_response = await client.get("/pending")
            assert pending_response.status_code == 200
            assert "Integration helmet pricing request" in pending_response.text

            approval_response = await client.post(f"/api/drafts/{draft_id}/approve")
            assert approval_response.status_code == 200
            approval_payload = approval_response.json()
            assert approval_payload["success"] is True
            assert approval_payload["status"] == "approved"
            assert approval_payload["audit"]["action"] == "approved"
            assert approval_payload["audit"]["approver"] == "John Doe"
            assert approval_payload["audit"]["approver_username"] == "john"

            refreshed_queue = await client.get("/api/drafts/")
            assert refreshed_queue.status_code == 200
            assert all(item["draft_id"] != draft_id for item in refreshed_queue.json())

            audit_response = await client.get("/api/audits/")
            assert audit_response.status_code == 200
            assert any(
                item["draft_id"] == draft_id
                and item["action"] == "approved"
                and item["approver_username"] == "john"
                for item in audit_response.json()
            )

        assert get_state_repository().get_draft(draft_id) is None
    finally:
        reset_app_settings()
