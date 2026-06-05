from datetime import datetime

from app.crews.sales_inquiry_crew import run_sales_inquiry_workflow
from app.schemas.draft import EmailPayload, DraftResponse
from app.schemas.email import IncomingEmail


class DraftService:
    def __init__(self):
        self.drafts = {}

    async def generate_draft(self, email: EmailPayload) -> DraftResponse:
        workflow = run_sales_inquiry_workflow(
            IncomingEmail(
                sender=email.sender,
                subject=email.subject,
                body=email.body,
            )
        )

        draft = DraftResponse(
            draft_id=workflow.draft_id,
            sender=email.sender,
            subject=email.subject,
            customer_inquiry=workflow.customer_inquiry,
            ai_draft=workflow.ai_draft,
            status=workflow.status,
        )

        self.drafts[workflow.draft_id] = {
            **draft.model_dump(),
            "workflow": workflow.model_dump(),
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
