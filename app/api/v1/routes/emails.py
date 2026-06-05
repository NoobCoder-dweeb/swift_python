import json
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request

from app.schemas.email import IncomingEmail
from app.services.email_parser import (
    EmailParseError,
    incoming_email_from_mapping,
    parse_rfc822_email,
)
from app.services.email_service import EmailService

router = APIRouter()

email_service = EmailService()


@router.post("/receive")
async def receive_email(email: IncomingEmail):
    """
    Endpoint called by email listener.
    """
    return await email_service.process_email(email)


@router.post("/ingest")
async def ingest_email(request: Request):
    """
    Dummy email receiver for curl-driven local testing.

    Accepts JSON/form payloads with sender/from, subject, and body fields, or a
    raw RFC822-style email body with From and Subject headers.
    """
    try:
        email = await _email_from_request(request)
    except EmailParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await email_service.ingest_email(email)


@router.get("/queue")
async def get_email_queue():
    return email_service.get_queue()


@router.post("/{email_id}/reprocess")
async def reprocess_email(email_id: str):
    return await email_service.reprocess(email_id)


async def _email_from_request(request: Request) -> IncomingEmail:
    content_type = (request.headers.get("content-type") or "").split(";")[0].lower()

    if content_type == "application/json":
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise EmailParseError("JSON email payload is invalid.") from exc
        if not isinstance(payload, dict):
            raise EmailParseError("JSON email payload must be an object.")
        return incoming_email_from_mapping(payload)

    if content_type == "multipart/form-data":
        form = await request.form()
        return incoming_email_from_mapping(form)

    raw_body = await request.body()
    if content_type == "application/x-www-form-urlencoded":
        form_payload = {
            key: values[-1]
            for key, values in parse_qs(
                raw_body.decode("utf-8", errors="replace")
            ).items()
        }
        if any(
            key in form_payload for key in ("sender", "from", "body", "message", "text")
        ):
            return incoming_email_from_mapping(form_payload)

    return parse_rfc822_email(raw_body)
