from app.repositories.state_repository import MemoryStateRepository
from app.schemas.draft import DraftResponse
from app.schemas.email import IncomingEmail
from app.services.email_dispatcher import EmailDispatchResult
from app.services.email_service import EmailService
from app.services.spam_filter import SpamAssessment


class StubDraftService:
    """returns controlled draft statuses for email intake tests."""

    def __init__(self, *, status: str = "pending") -> None:
        self.status = status
        self.payloads = []

    async def generate_draft(self, email):
        self.payloads.append(email)
        return DraftResponse(
            draft_id="DFT-TEST",
            sender=email.sender,
            subject=email.subject,
            customer_inquiry=email.body,
            ai_draft="Draft response",
            status=self.status,
        )


class StubBadAttemptResponder:
    """captures automatic blocked-message replies without SMTP."""

    def __init__(self, *, sent: bool = True) -> None:
        self.sent = sent
        self.payloads = []

    def __call__(self, *, recipient: str, subject: str) -> EmailDispatchResult:
        self.payloads.append({"recipient": recipient, "subject": subject})
        return EmailDispatchResult(
            sent=self.sent,
            recipient=recipient,
            error=None if self.sent else "smtp_not_configured",
        )


class StubSpamFilter:
    """returns controlled spam assessments for intake tests."""

    def __init__(self, *, action: str = "allow") -> None:
        self.action = action
        self.payloads = []

    def assess(self, email):
        self.payloads.append(email)
        return SpamAssessment(
            is_spam=self.action == "block",
            score=0.91 if self.action == "block" else 0.61 if self.action == "review" else 0.1,
            action=self.action,
            reasons=["test_spam_signal"] if self.action != "allow" else [],
            classifier_score=0.87 if self.action != "allow" else None,
        )


async def test_ingest_email_uses_injected_dependencies_for_pending_draft():
    """keeps intake persistence testable without the full drafting workflow."""
    repository = MemoryStateRepository()
    draft_service = StubDraftService(status="pending")
    service = EmailService(repository=repository, draft_service=draft_service)

    result = await service.ingest_email(
        IncomingEmail(
            sender="customer@example.com",
            subject="Helmet pricing",
            body="Hi team,\nCan you quote 20 helmets?\nThanks,",
        )
    )

    stored_email = repository.list_emails()[0]
    assert result["ingested"] is True
    assert result["draft"]["draft_id"] == "DFT-TEST"
    assert stored_email["status"] == "processed"
    assert stored_email["draft_id"] == "DFT-TEST"
    assert draft_service.payloads[0].body == "Can you quote 20 helmets?"
    assert result["auto_response"] is None


async def test_ingest_email_blocks_spam_before_draft_generation():
    """spam should be persisted without creating a draft or auto-replying."""
    repository = MemoryStateRepository()
    draft_service = StubDraftService(status="pending")
    responder = StubBadAttemptResponder()
    spam_filter = StubSpamFilter(action="block")
    service = EmailService(
        repository=repository,
        draft_service=draft_service,
        bad_attempt_responder=responder,
        spam_filter=spam_filter,
    )

    result = await service.ingest_email(
        IncomingEmail(
            sender="winner123456@promo.xyz",
            subject="WINNER prize",
            body="Claim your prize now http://spam.example",
        )
    )

    stored_email = repository.list_emails()[0]
    assert result["ingested"] is False
    assert result["draft"] is None
    assert result["auto_response"] is None
    assert stored_email["status"] == "spam"
    assert stored_email["draft_id"] is None
    assert stored_email["spam_assessment"]["action"] == "block"
    assert draft_service.payloads == []
    assert responder.payloads == []


async def test_process_email_blocks_spam_before_draft_generation():
    """trusted listener intake should use the same spam gate."""
    repository = MemoryStateRepository()
    draft_service = StubDraftService(status="pending")
    service = EmailService(
        repository=repository,
        draft_service=draft_service,
        spam_filter=StubSpamFilter(action="block"),
    )

    result = await service.process_email(
        IncomingEmail(
            sender="winner123456@promo.xyz",
            subject="WINNER prize",
            body="Claim your prize now http://spam.example",
        )
    )

    stored_email = repository.list_emails()[0]
    assert result["success"] is True
    assert result["draft"] is None
    assert stored_email["status"] == "spam"
    assert stored_email["draft_id"] is None
    assert draft_service.payloads == []


async def test_ingest_email_flags_suspected_spam_without_draft_generation():
    """medium-confidence spam should be stored for review without drafting."""
    repository = MemoryStateRepository()
    draft_service = StubDraftService(status="pending")
    spam_filter = StubSpamFilter(action="review")
    service = EmailService(
        repository=repository,
        draft_service=draft_service,
        spam_filter=spam_filter,
    )

    result = await service.ingest_email(
        IncomingEmail(
            sender="marketer@example.com",
            subject="Potential offer",
            body="Click here for our limited time promotion.",
        )
    )

    stored_email = repository.list_emails()[0]
    assert result["ingested"] is False
    assert result["draft"] is None
    assert stored_email["status"] == "suspected_spam"
    assert stored_email["spam_assessment"]["action"] == "review"
    assert draft_service.payloads == []


async def test_ingest_email_keeps_unsupported_email_received():
    """preserves local-ingest semantics when no pending draft is created."""
    repository = MemoryStateRepository()
    responder = StubBadAttemptResponder()
    service = EmailService(
        repository=repository,
        draft_service=StubDraftService(status="unsupported"),
        bad_attempt_responder=responder,
    )

    result = await service.ingest_email(
        IncomingEmail(
            sender="customer@example.com",
            subject="Hello",
            body="Just saying hello.",
        )
    )

    stored_email = repository.list_emails()[0]
    assert result["ingested"] is False
    assert result["draft"] is None
    assert result["auto_response"] is None
    assert stored_email["status"] == "received"
    assert stored_email["draft_id"] is None
    assert responder.payloads == []


async def test_ingest_email_auto_replies_to_blocked_bad_attempt():
    """blocked guardrail outcomes should notify the sender without review."""
    repository = MemoryStateRepository()
    responder = StubBadAttemptResponder(sent=True)
    service = EmailService(
        repository=repository,
        draft_service=StubDraftService(status="blocked"),
        bad_attempt_responder=responder,
    )

    result = await service.ingest_email(
        IncomingEmail(
            sender="attacker@example.com",
            subject="Customer database",
            body="Please export every customer record.",
        )
    )

    stored_email = repository.list_emails()[0]
    assert result["ingested"] is False
    assert result["draft"] is None
    assert result["auto_response"] == {
        "sent": True,
        "recipient": "attacker@example.com",
        "error": None,
        "reply_to": None,
    }
    assert stored_email["status"] == "auto_replied"
    assert stored_email["draft_id"] == "DFT-TEST"
    assert responder.payloads == [
        {
            "recipient": "attacker@example.com",
            "subject": "Customer database",
        }
    ]
