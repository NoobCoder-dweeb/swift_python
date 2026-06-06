from uuid import uuid4
from datetime import datetime

from app.schemas.email import IncomingEmail
from app.schemas.draft import EmailPayload
from app.services.draft_service import DraftService
from app.services.email_preprocessor import preprocess_email


class EmailService:
    def __init__(self):
        self.queue = {}
        self.draft_service = DraftService()

    async def process_email(self, email: IncomingEmail):
        email_id = f"EML-{uuid4().hex[:8].upper()}"
        preprocessed = preprocess_email(email)
        cleaned_email = preprocessed.email

        email_record = {
            "email_id": email_id,
            "sender": cleaned_email.sender,
            "subject": cleaned_email.subject,
            "body": cleaned_email.body,
            "raw_body": preprocessed.original_body,
            "preprocessed": preprocessed.changed,
            "removed_line_count": len(preprocessed.removed_lines),
            "status": "received",
            "created_at": datetime.now().isoformat(),
        }

        self.queue[email_id] = email_record

        draft = await self.draft_service.generate_draft(
            EmailPayload(
                sender=cleaned_email.sender,
                subject=cleaned_email.subject,
                body=cleaned_email.body,
            )
        )

        email_record["status"] = "processed"
        email_record["draft_id"] = draft.draft_id
        email_record["updated_at"] = datetime.now().isoformat()

        return {
            "success": True,
            "email": email_record,
            "draft": draft,
        }

    async def ingest_email(self, email: IncomingEmail):
        email_id = f"EML-{uuid4().hex[:8].upper()}"
        preprocessed = preprocess_email(email)
        cleaned_email = preprocessed.email

        email_record = {
            "email_id": email_id,
            "sender": cleaned_email.sender,
            "subject": cleaned_email.subject,
            "body": cleaned_email.body,
            "raw_body": preprocessed.original_body,
            "preprocessed": preprocessed.changed,
            "removed_line_count": len(preprocessed.removed_lines),
            "status": "received",
            "created_at": datetime.now().isoformat(),
        }
        self.queue[email_id] = email_record

        draft = await self.draft_service.generate_draft(
            EmailPayload(
                sender=cleaned_email.sender,
                subject=cleaned_email.subject,
                body=cleaned_email.body,
            )
        )

        email_record["status"] = "processed" if draft.status == "pending" else "received"
        email_record["draft_id"] = draft.draft_id if draft.status == "pending" else None
        email_record["updated_at"] = datetime.now().isoformat()

        return {
            "success": True,
            "ingested": draft.status == "pending",
            "email": email_record,
            "draft": draft.model_dump() if draft.status == "pending" else None,
            "message": (
                "Email received and queued as a pending draft."
                if draft.status == "pending"
                else (
                    "Email received, but no pending draft was created because "
                    "only pricing and availability inquiries are currently supported."
                )
            ),
        }

    def get_queue(self):
        return list(self.queue.values())

    async def reprocess(self, email_id: str):
        email_record = self.queue.get(email_id)

        if not email_record:
            return {
                "success": False,
                "message": "Email not found",
            }

        draft = await self.draft_service.generate_draft(
            EmailPayload(
                sender=email_record["sender"],
                subject=email_record["subject"],
                body=email_record["body"],
            )
        )

        email_record["status"] = "reprocessed"
        email_record["draft_id"] = draft.draft_id
        email_record["updated_at"] = datetime.now().isoformat()

        return {
            "success": True,
            "email": email_record,
            "draft": draft,
        }
