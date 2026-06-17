import base64
import binascii
import hmac
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_app_settings
from app.schemas.email import IncomingEmail
from app.services.email_parser import (
    EmailParseError,
    incoming_email_from_cloudmailin,
    incoming_email_from_mapping,
    parse_rfc822_email,
)
from app.services.email_service import EmailService

router = APIRouter()

email_service = EmailService()


@router.post("/receive")
async def receive_email(email: IncomingEmail):
    """
    gives automated listeners a structured path into the drafting workflow.
    """
    return await email_service.process_email(email)


@router.post("/ingest")
async def ingest_email(request: Request):
    """
    accepts realistic local inputs so ingestion can be tested without mail infra.

    Accepts JSON/form payloads with sender/from, subject, and body fields, or a
    raw RFC822-style email body with From and Subject headers.
    """
    try:
        email = await _email_from_request(request)
    except EmailParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await email_service.ingest_email(email)


@router.post("/cloudmailin")
async def receive_cloudmailin_email(request: Request):
    """
    receives CloudMailin JSON Normalized webhooks through a public tunnel.
    """
    _verify_cloudmailin_basic_auth(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="CloudMailin JSON is invalid."
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400, detail="CloudMailin JSON must be an object."
        )

    try:
        email = incoming_email_from_cloudmailin(payload)
    except EmailParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await email_service.ingest_email(email)


@router.get("/queue")
async def get_email_queue():
    """lets operators inspect stored email intake history."""
    return email_service.get_queue()


@router.post("/{email_id}/reprocess")
async def reprocess_email(email_id: str):
    """reruns draft generation when stored intake needs another pass."""
    return await email_service.reprocess(email_id)


async def _email_from_request(request: Request) -> IncomingEmail:
    """normalizes JSON, form, and raw email bodies into one schema."""
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


def _verify_cloudmailin_basic_auth(request: Request) -> None:
    """requires the tunnel-facing CloudMailin endpoint to use Basic Auth."""
    settings = get_app_settings()
    if not settings.cloudmailin_auth_configured:
        raise HTTPException(
            status_code=503,
            detail="CloudMailin Basic Auth is not configured.",
        )

    username, password = _basic_auth_credentials(
        request.headers.get("authorization") or ""
    )
    username_matches = hmac.compare_digest(
        username,
        settings.cloudmailin_basic_username,
    )
    password_matches = hmac.compare_digest(
        password,
        settings.cloudmailin_basic_password,
    )
    if not username_matches or not password_matches:
        raise HTTPException(
            status_code=401,
            detail="Invalid CloudMailin credentials.",
            headers={"WWW-Authenticate": 'Basic realm="cloudmailin"'},
        )


def _basic_auth_credentials(header: str) -> tuple[str, str]:
    """decodes a Basic Auth header without leaking parsing details to callers."""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return "", ""
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return "", ""
    username, separator, password = decoded.partition(":")
    if not separator:
        return "", ""
    return username, password
