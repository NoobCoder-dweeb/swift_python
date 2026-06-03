from fastapi import APIRouter

from app.schemas.email import IncomingEmail
from app.services.email_service import EmailService

router = APIRouter()

email_service = EmailService()


@router.post("/receive")
async def receive_email(email: IncomingEmail):
    """
    Endpoint called by email listener.
    """
    return await email_service.process_email(email)


@router.get("/queue")
async def get_email_queue():
    return email_service.get_queue()


@router.post("/{email_id}/reprocess")
async def reprocess_email(email_id: str):
    return await email_service.reprocess(email_id)
