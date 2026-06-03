from uuid import uuid4
from datetime import datetime

from app.schemas.draft import EmailPayload, DraftResponse


class DraftService:
    def __init__(self):
        self.drafts = {}

    async def generate_draft(self, email: EmailPayload) -> DraftResponse:
        draft_id = f"DFT-{uuid4().hex[:8].upper()}"

        draft = DraftResponse(
            draft_id=draft_id,
            sender=email.sender,
            subject=email.subject,
            customer_inquiry=email.body,
            ai_draft=(
                "Dear Customer,\n\n"
                "Thank you for your inquiry. "
                "We are currently checking the requested product details, "
                "stock availability, and pricing information.\n\n"
                "A sales representative will review this draft before it is sent.\n\n"
                "Best regards,\n"
                "Safetyware Sales Team"
            ),
            status="pending",
        )

        self.drafts[draft_id] = {
            **draft.model_dump(),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        return draft

    def list_drafts(self):
        return list(self.drafts.values())

    def get_draft(self, draft_id: str):
        return self.drafts.get(draft_id)

    def approve_draft(self, draft_id: str):
        draft = self.drafts.get(draft_id)

        if not draft:
            return {
                "success": False,
                "message": "Draft not found",
            }

        draft["status"] = "approved"
        draft["updated_at"] = datetime.now().isoformat()

        return {
            "success": True,
            "draft_id": draft_id,
            "status": "approved",
            "message": "Draft approved and queued for dispatch.",
        }

    def reject_draft(self, draft_id: str, reason: str = ""):
        draft = self.drafts.get(draft_id)

        if not draft:
            return {
                "success": False,
                "message": "Draft not found",
            }

        draft["status"] = "rejected"
        draft["rejection_reason"] = reason
        draft["updated_at"] = datetime.now().isoformat()

        return {
            "success": True,
            "draft_id": draft_id,
            "status": "rejected",
            "reason": reason,
            "message": "Draft rejected and marked for regeneration.",
        }
