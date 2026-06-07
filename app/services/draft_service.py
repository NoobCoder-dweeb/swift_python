import asyncio

from app.crews.sales_inquiry_crew import run_sales_inquiry_workflow
from app.repositories.state_repository import get_state_repository
from app.schemas.draft import EmailPayload, DraftResponse
from app.schemas.email import IncomingEmail
from data import (
    add_generated_draft,
    approve_draft as approve_pending_draft,
    get_drafts,
    reject_and_regenerate_draft,
)


class DraftService:
    def __init__(self):
        self.repository = get_state_repository()

    async def generate_draft(self, email: EmailPayload) -> DraftResponse:
        workflow = await asyncio.to_thread(
            run_sales_inquiry_workflow,
            IncomingEmail(
                sender=email.sender,
                subject=email.subject,
                body=email.body,
            ),
        )
        stored_draft = add_generated_draft(
            {
                "from": email.sender,
                "subject": email.subject,
                "body": workflow.customer_inquiry,
            },
            draft_id=workflow.draft_id,
            ai_draft=workflow.ai_draft,
            status=workflow.status,
            workflow=workflow.model_dump(),
        )
        draft_id = stored_draft.draft_id if stored_draft else workflow.draft_id

        draft = DraftResponse(
            draft_id=draft_id,
            sender=email.sender,
            subject=email.subject,
            customer_inquiry=workflow.customer_inquiry,
            ai_draft=workflow.ai_draft,
            status=workflow.status,
        )

        return draft

    def list_drafts(self):
        return [draft.to_dict() for draft in get_drafts()]

    def get_draft(self, draft_id: str):
        row = self.repository.get_draft(draft_id)
        if row:
            return next(
                (draft.to_dict() for draft in get_drafts() if draft.draft_id == draft_id),
                {
                    **row,
                    "customer_inquiry": row["body"],
                    "ai_draft": row.get("ai_draft_text", ""),
                },
            )
        return None

    def approve_draft(self, draft_id: str):
        audit = approve_pending_draft(draft_id, approver="Sales Officer")
        if not audit:
            return {
                "success": False,
                "message": "Draft not found",
            }

        return {
            "success": True,
            "draft_id": draft_id,
            "status": "approved",
            "audit": audit,
            "message": "Draft approved and queued for dispatch.",
        }

    def reject_draft(self, draft_id: str, reason: str = ""):
        regenerated = reject_and_regenerate_draft(
            draft_id,
            requester="Sales Officer",
            rejection_reason=reason,
        )
        if not regenerated:
            return {
                "success": False,
                "message": "Draft not found",
            }

        return {
            "success": True,
            "draft_id": draft_id,
            "status": "pending",
            "reason": reason,
            "draft": regenerated,
            "message": "Draft rejected and regenerated for review.",
        }
