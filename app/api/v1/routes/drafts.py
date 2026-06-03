from fastapi import APIRouter, HTTPException
from app.schemas.draft import EmailPayload, DraftResponse
from app.services.draft_service import DraftService

router = APIRouter()

draft_service = DraftService()


@router.post("/", response_model=DraftResponse)
async def create_draft(email: EmailPayload):
    """
    Generate a draft from customer inquiry.
    """
    return await draft_service.generate_draft(email)


@router.get("/")
async def list_drafts():
    return draft_service.list_drafts()


@router.get("/{draft_id}")
async def get_draft(draft_id: str):
    draft = draft_service.get_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    return draft


@router.post("/{draft_id}/approve")
async def approve_draft(draft_id: str):
    return draft_service.approve_draft(draft_id)


@router.post("/{draft_id}/reject")
async def reject_draft(draft_id: str, reason: str = ""):
    return draft_service.reject_draft(draft_id, reason)
