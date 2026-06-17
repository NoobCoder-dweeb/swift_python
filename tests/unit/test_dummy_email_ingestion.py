import httpx
import json

from app.api.v1.routes.emails import email_service
from app.core.config import reset_app_settings
from app.main import app


async def test_ingest_raw_email_creates_pending_draft():
    """verifies real email payloads can enter the review workflow."""
    raw_email = (
        b"From: curl.customer@example.com\r\n"
        b"To: sales@example.com\r\n"
        b"Subject: Curl safety helmet stock\r\n"
        b"\r\n"
        b"Do you have 50 safety helmets in stock this week?"
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
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


async def test_ingest_json_accepts_from_alias():
    """supports webhook payloads that use from instead of sender."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
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


async def test_cloudmailin_json_webhook_creates_pending_draft(monkeypatch):
    """CloudMailin JSON Normalized webhooks enter the review workflow."""
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_USERNAME", "cloudmailin")
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_PASSWORD", "secret")
    reset_app_settings()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            auth=("cloudmailin", "secret"),
        ) as client:
            response = await client.post(
                "/api/emails/cloudmailin",
                json={
                    "headers": {
                        "from": "Personal Gmail <personal.gmail@example.com>",
                        "subject": "Product X pricing from Gmail",
                    },
                    "envelope": {
                        "from": "personal.gmail@example.com",
                        "to": "swift@example.cloudmailin.net",
                    },
                    "plain": "Older quoted content",
                    "reply_plain": "Can I get pricing for 40 units of Product X?",
                    "attachments": [],
                },
            )
    finally:
        reset_app_settings()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ingested"] is True
    assert payload["email"]["sender"] == "personal.gmail@example.com"
    assert payload["email"]["subject"] == "Product X pricing from Gmail"
    assert payload["email"]["body"] == "Can I get pricing for 40 units of Product X?"
    assert payload["draft"]["status"] == "pending"


async def test_cloudmailin_form_webhook_creates_pending_draft(monkeypatch):
    """CloudMailin form-style posts still enter the review workflow."""
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_USERNAME", "cloudmailin")
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_PASSWORD", "secret")
    reset_app_settings()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            auth=("cloudmailin", "secret"),
        ) as client:
            response = await client.post(
                "/api/emails/cloudmailin",
                data={
                    "from": "personal.gmail@example.com",
                    "subject": "Product X pricing from Gmail",
                    "plain": "Can I get pricing for 40 units of Product X?",
                },
            )
    finally:
        reset_app_settings()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ingested"] is True
    assert payload["email"]["sender"] == "personal.gmail@example.com"
    assert payload["email"]["body"] == "Can I get pricing for 40 units of Product X?"


async def test_cloudmailin_multipart_with_json_envelope_creates_pending_draft(
    monkeypatch,
):
    """CloudMailin multipart posts may encode headers/envelope as JSON strings."""
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_USERNAME", "cloudmailin")
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_PASSWORD", "secret")
    reset_app_settings()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            auth=("cloudmailin", "secret"),
        ) as client:
            response = await client.post(
                "/api/emails/cloudmailin",
                files={
                    "headers": (
                        None,
                        json.dumps(
                            {
                                "from": "Shaun Koay <shaukoay.dev@gmail.com>",
                                "subject": "Inquiry for Safety Gloves",
                            }
                        ),
                    ),
                    "envelope": (
                        None,
                        json.dumps(
                            {
                                "from": "shaukoay.dev@gmail.com",
                                "to": "76ebabb5c6c20727246b@cloudmailin.net",
                            }
                        ),
                    ),
                    "plain": (
                        None,
                        "I would like pricing and stock level of Product X.",
                    ),
                },
            )
    finally:
        reset_app_settings()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ingested"] is True
    assert payload["email"]["sender"] == "shaukoay.dev@gmail.com"
    assert payload["email"]["subject"] == "Inquiry for Safety Gloves"


async def test_cloudmailin_multipart_with_bracket_fields_creates_pending_draft(
    monkeypatch,
):
    """CloudMailin multipart normalized fields use bracket-style names."""
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_USERNAME", "cloudmailin")
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_PASSWORD", "secret")
    reset_app_settings()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            auth=("cloudmailin", "secret"),
        ) as client:
            response = await client.post(
                "/api/emails/cloudmailin",
                files={
                    "headers[from]": (
                        None,
                        "Shaun Koay <shaukoay.dev@gmail.com>",
                    ),
                    "headers[subject]": (None, "Inquiry for Safety Gloves"),
                    "envelope[from]": (None, "shaukoay.dev@gmail.com"),
                    "plain": (
                        None,
                        "I would like pricing and stock level of Product X.",
                    ),
                },
            )
    finally:
        reset_app_settings()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ingested"] is True
    assert payload["email"]["sender"] == "shaukoay.dev@gmail.com"
    assert payload["email"]["subject"] == "Inquiry for Safety Gloves"


async def test_cloudmailin_webhook_requires_basic_auth(monkeypatch):
    """public tunnel webhook rejects requests without configured credentials."""
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_USERNAME", "cloudmailin")
    monkeypatch.setenv("SWIFT_CLOUDMAILIN_BASIC_PASSWORD", "secret")
    reset_app_settings()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/emails/cloudmailin",
                json={
                    "headers": {
                        "from": "Personal Gmail <personal.gmail@example.com>",
                        "subject": "Product X pricing from Gmail",
                    },
                    "plain": "Can I get pricing for 40 units of Product X?",
                },
            )
    finally:
        reset_app_settings()

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="cloudmailin"'


async def test_ingest_json_blocks_customer_information_as_product():
    """sensitive customer information must not become a pending draft."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/emails/ingest",
            json={
                "from": "customer@example.com",
                "subject": "Product pricing request",
                "body": "Can I get pricing for 40 units of customer information?",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ingested"] is False
    assert payload["draft"] is None
    assert payload["email"]["status"] == "received"
    assert payload["email"]["draft_id"] is None


async def test_ingest_preprocesses_irrelevant_email_content():
    """ensures noisy email threads are cleaned before draft generation."""
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

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
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
