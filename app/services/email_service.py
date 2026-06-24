from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.repositories.state_repository import StateRepository, get_state_repository
from app.schemas.draft import DraftResponse, EmailPayload
from app.schemas.email import IncomingEmail
from app.services.email_dispatcher import (
    EmailDispatchResult,
    send_bad_attempt_response,
)
from app.services.draft_service import DraftService
from app.services.email_preprocessor import preprocess_email
from app.services.spam_filter import HybridSpamFilter, SpamFilter
from data import build_email_thread_context


class DraftGenerator(Protocol):
    """keeps email intake independent from the concrete draft workflow service."""

    async def generate_draft(self, email: EmailPayload) -> DraftResponse:
        """returns a generated draft for a cleaned customer inquiry."""
        ...


class BadAttemptResponder(Protocol):
    """sends the automatic customer notice for blocked intake."""

    def __call__(
        self,
        *,
        recipient: str,
        subject: str,
    ) -> EmailDispatchResult:
        """returns SMTP delivery details for audit-friendly responses."""
        ...


class EmailService:
    """persists incoming emails and connects them to generated sales drafts."""

    def __init__(
        self,
        *,
        repository: StateRepository | None = None,
        draft_service: DraftGenerator | None = None,
        bad_attempt_responder: BadAttemptResponder | None = None,
        spam_filter: SpamFilter | None = None,
    ) -> None:
        """keeps dependencies injectable while preserving default app wiring."""
        self.repository = repository or get_state_repository()
        self.draft_service = draft_service or DraftService()
        self.bad_attempt_responder = bad_attempt_responder or send_bad_attempt_response
        self.spam_filter = spam_filter or HybridSpamFilter()

    async def process_email(self, email: IncomingEmail):
        """supports structured email intake from trusted listeners."""
        email_record = self._create_email_record(email)
        spam_response = self._complete_if_spam(email_record)
        if spam_response:
            return spam_response

        draft = await self._generate_draft_from_record(email_record)
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
        email_record = self._create_email_record(email)
        spam_response = self._complete_if_spam(email_record)
        if spam_response:
            return {
                **spam_response,
                "ingested": False,
                "auto_response": None,
            }

        draft = await self._generate_draft_from_record(email_record)
        ingested = draft.status == "pending"
        bad_attempt_response = (
            self._send_bad_attempt_response(email_record)
            if draft.status == "blocked"
            else None
        )
        auto_replied = bool(bad_attempt_response and bad_attempt_response.sent)
        self._complete_email_record(
            email_record,
            status=(
                "processed"
                if ingested
                else "auto_replied"
                if auto_replied
                else "received"
            ),
            draft_id=draft.draft_id if ingested or auto_replied else None,
        )

        return {
            "success": True,
            "ingested": ingested,
            "email": email_record,
            "draft": draft.model_dump() if ingested else None,
            "auto_response": _dispatch_result_dict(bad_attempt_response),
            "message": (
                "Email received and queued as a pending draft."
                if ingested
                else "Email received and an automatic bad-attempt response was sent."
                if auto_replied
                else (
                    "Email received, but no pending draft was created because "
                    "only pricing and availability inquiries are currently supported."
                )
            ),
        }

    def _complete_if_spam(self, email_record: dict) -> dict | None:
        """persists spam decisions before any draft generation happens."""
        spam_assessment = self.spam_filter.assess(
            IncomingEmail(
                sender=email_record["sender"],
                subject=email_record["subject"],
                body=email_record["body"],
            )
        )
        email_record["spam_assessment"] = _spam_assessment_dict(spam_assessment)
        if spam_assessment.action not in {"block", "review"}:
            return None

        status = "spam" if spam_assessment.action == "block" else "suspected_spam"
        self._complete_email_record(
            email_record,
            status=status,
            draft_id=None,
        )
        return {
            "success": True,
            "email": email_record,
            "draft": None,
            "message": (
                "Email flagged as spam and no draft was created."
                if status == "spam"
                else "Email flagged as suspected spam for review and no draft was created."
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
        email_record = self._create_email_record(email)
        draft = await self._generate_draft_from_record(email_record)
        return email_record, draft

    def _create_email_record(self, email: IncomingEmail) -> dict:
        """preprocesses and persists the initial received email record."""
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
        return email_record

    async def _generate_draft_from_record(self, email_record: dict) -> DraftResponse:
        """adapts persisted email rows to the draft-generation contract."""
        return await self.draft_service.generate_draft(
            EmailPayload(
                sender=email_record["sender"],
                subject=email_record["subject"],
                body=email_record["body"],
                conversation_context=build_email_thread_context(
                    sender=email_record["sender"],
                    subject=email_record["subject"],
                    body=email_record["body"],
                    created=email_record.get("created_at"),
                ),
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

    def _send_bad_attempt_response(
        self,
        email_record: dict,
    ) -> EmailDispatchResult:
        """keeps blocked intake from entering review while notifying the sender."""
        return self.bad_attempt_responder(
            recipient=email_record["sender"],
            subject=email_record["subject"],
        )


def _new_id(prefix: str) -> str:
    """returns short stable IDs for persisted workflow rows."""
    return f"{prefix}-{uuid4().hex[:8].upper()}"


def _timestamp() -> str:
    """keeps timestamp formatting consistent across intake updates."""
    return datetime.now().isoformat()


def _dispatch_result_dict(result: EmailDispatchResult | None) -> dict | None:
    """serializes optional SMTP results for webhook/API callers."""
    if result is None:
        return None
    return {
        "sent": result.sent,
        "recipient": result.recipient,
        "error": result.error,
        "reply_to": result.reply_to,
    }


def _spam_assessment_dict(result) -> dict:
    """serializes spam-filter evidence into the email payload."""
    return {
        "is_spam": result.is_spam,
        "score": result.score,
        "action": result.action,
        "reasons": result.reasons,
        "classifier_score": result.classifier_score,
    }
