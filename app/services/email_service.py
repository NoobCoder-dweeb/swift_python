from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.repositories.state_repository import StateRepository, get_state_repository
from app.schemas.draft import DraftResponse, EmailPayload
from app.schemas.email import IncomingEmail
from app.services.draft_service import DraftService
from app.services.email_preprocessor import preprocess_email


class DraftGenerator(Protocol):
    """keeps email intake independent from the concrete draft workflow service."""

    async def generate_draft(self, email: EmailPayload) -> DraftResponse:
        """returns a generated draft for a cleaned customer inquiry."""
        ...


class EmailService:
    """persists incoming emails and connects them to generated sales drafts."""

    def __init__(
        self,
        *,
        repository: StateRepository | None = None,
        draft_service: DraftGenerator | None = None,
    ) -> None:
        """keeps dependencies injectable while preserving default app wiring."""
        self.repository = repository or get_state_repository()
        self.draft_service = draft_service or DraftService()

    async def process_email(self, email: IncomingEmail):
        """supports structured email intake from trusted listeners."""
        email_record, draft = await self._create_record_and_draft(email)
        self._complete_email_record(
            email_record,
            status="processed",
            draft_id=draft.draft_id,
        )

        return {
            "success": True,
            "email": email_record,
            "draft": draft,
        }

    async def ingest_email(self, email: IncomingEmail):
        """supports local/manual ingestion while preserving the same persisted flow."""
        email_record, draft = await self._create_record_and_draft(email)
        ingested = draft.status == "pending"
        self._complete_email_record(
            email_record,
            status="processed" if ingested else "received",
            draft_id=draft.draft_id if ingested else None,
        )

        return {
            "success": True,
            "ingested": ingested,
            "email": email_record,
            "draft": draft.model_dump() if ingested else None,
            "message": (
                "Email received and queued as a pending draft."
                if ingested
                else (
                    "Email received, but no pending draft was created because "
                    "only pricing and availability inquiries are currently supported."
                )
            ),
        }

    def get_queue(self):
        """exposes stored email intake history without relying on process memory."""
        return self.repository.list_emails()

    async def reprocess(self, email_id: str):
        """lets operators regenerate a draft from the original cleaned email."""
        email_record = self.repository.get_email(email_id)

        if not email_record:
            return {
                "success": False,
                "message": "Email not found",
            }

        draft = await self._generate_draft_from_record(email_record)

        self._complete_email_record(
            email_record,
            status="reprocessed",
            draft_id=draft.draft_id,
        )

        return {
            "success": True,
            "email": email_record,
            "draft": draft,
        }

    async def _create_record_and_draft(
        self,
        email: IncomingEmail,
    ) -> tuple[dict, DraftResponse]:
        """preprocesses, persists, then generates a draft for a new email."""
        preprocessed = preprocess_email(email)
        email_record = {
            "email_id": _new_id("EML"),
            "sender": preprocessed.email.sender,
            "subject": preprocessed.email.subject,
            "body": preprocessed.email.body,
            "raw_body": preprocessed.original_body,
            "preprocessed": preprocessed.changed,
            "removed_line_count": len(preprocessed.removed_lines),
            "status": "received",
            "created_at": _timestamp(),
        }
        self.repository.upsert_email(email_record)

        draft = await self._generate_draft_from_record(email_record)
        return email_record, draft

    async def _generate_draft_from_record(self, email_record: dict) -> DraftResponse:
        """adapts persisted email rows to the draft-generation contract."""
        return await self.draft_service.generate_draft(
            EmailPayload(
                sender=email_record["sender"],
                subject=email_record["subject"],
                body=email_record["body"],
            )
        )

    def _complete_email_record(
        self,
        email_record: dict,
        *,
        status: str,
        draft_id: str | None,
    ) -> None:
        """persists the final intake status after draft generation."""
        email_record["status"] = status
        email_record["draft_id"] = draft_id
        email_record["updated_at"] = _timestamp()
        self.repository.upsert_email(email_record)


def _new_id(prefix: str) -> str:
    """returns short stable IDs for persisted workflow rows."""
    return f"{prefix}-{uuid4().hex[:8].upper()}"


def _timestamp() -> str:
    """keeps timestamp formatting consistent across intake updates."""
    return datetime.now().isoformat()
