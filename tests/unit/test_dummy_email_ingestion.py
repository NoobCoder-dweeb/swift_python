from fastapi.testclient import TestClient

from app.api.v1.routes.emails import email_service
from app.main import app


def test_ingest_raw_email_creates_pending_draft():
    """verifies real email payloads can enter the review workflow."""
    client = TestClient(app)
    raw_email = (
        b"From: curl.customer@example.com\r\n"
        b"To: sales@example.com\r\n"
        b"Subject: Curl safety helmet stock\r\n"
        b"\r\n"
        b"Do you have 50 safety helmets in stock this week?"
    )

    response = client.post(
        "/api/emails/ingest",
        content=raw_email,
        headers={"Content-Type": "message/rfc822"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ingested"] is True
    assert payload["email"]["sender"] == "curl.customer@example.com"
    assert payload["draft"]["sender"] == "curl.customer@example.com"
    assert payload["draft"]["subject"] == "Curl safety helmet stock"


def test_ingest_json_accepts_from_alias():
    """supports webhook payloads that use from instead of sender."""
    client = TestClient(app)

    response = client.post(
        "/api/emails/ingest",
        json={
            "from": "json.customer@example.com",
            "subject": "JSON Product X pricing request",
            "body": "Can I get pricing for 40 units of Product X?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ingested"] is True
    assert payload["email"]["draft_id"] == payload["draft"]["draft_id"]
    assert any(
        item["email_id"] == payload["email"]["email_id"]
        for item in email_service.get_queue()
    )


def test_ingest_preprocesses_irrelevant_email_content():
    """ensures noisy email threads are cleaned before draft generation."""
    client = TestClient(app)
    raw_email = (
        b"From: noisy.customer@example.com\r\n"
        b"To: sales@example.com\r\n"
        b"Subject: Noisy pricing and stock request\r\n"
        b"\r\n"
        b"Hi team,\r\n"
        b"\r\n"
        b"I hope you are well.\r\n"
        b"Can you share pricing for 40 safety helmets?\r\n"
        b"Please confirm stock availability for delivery next week.\r\n"
        b"\r\n"
        b"Thanks,\r\n"
        b"Jordan\r\n"
        b"Phone: +60 12 345 6789\r\n"
        b"-----Original Message-----\r\n"
        b"From: someone@example.com\r\n"
        b"Subject: old thread\r\n"
        b"Please ignore this old reply.\r\n"
    )

    response = client.post(
        "/api/emails/ingest",
        content=raw_email,
        headers={"Content-Type": "message/rfc822"},
    )

    assert response.status_code == 200
    payload = response.json()
    cleaned_body = payload["email"]["body"]

    assert payload["email"]["preprocessed"] is True
    assert payload["email"]["removed_line_count"] >= 2
    assert "Can you share pricing for 40 safety helmets?" in cleaned_body
    assert "Please confirm stock availability" in cleaned_body
    assert "I hope you are well" not in cleaned_body
    assert "Phone:" not in cleaned_body
    assert "Original Message" not in cleaned_body
    assert payload["draft"]["customer_inquiry"] == cleaned_body
