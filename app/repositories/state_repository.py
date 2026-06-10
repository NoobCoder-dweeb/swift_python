from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from app.core.config import get_app_settings


DraftRow = dict[str, Any]
AuditRow = dict[str, Any]
EmailRow = dict[str, Any]


class StateRepository(Protocol):
    """lets services stay stateless while storage can vary by environment."""

    def initialize(self) -> None:
        """prepares backing storage before request handlers use it."""
        ...

    def list_drafts(self) -> list[DraftRow]:
        """feeds review queues from the configured state store."""
        ...

    def get_draft(self, draft_id: str) -> DraftRow | None:
        """supports direct review and decision actions by stable ID."""
        ...

    def find_draft(
        self, *, sender: str, subject: str, body: str, status: str
    ) -> DraftRow | None:
        """prevents duplicate pending drafts for the same customer inquiry."""
        ...

    def upsert_draft(self, draft: DraftRow) -> DraftRow:
        """handles both initial persistence and regenerated draft updates."""
        ...

    def delete_draft(self, draft_id: str) -> None:
        """removes approved drafts from the pending review surface."""
        ...

    def list_audits(self) -> list[AuditRow]:
        """exposes decision history for compliance and UI timelines."""
        ...

    def get_audit(self, audit_id: str) -> AuditRow | None:
        """makes one recorded decision addressable by ID."""
        ...

    def find_audit(self, *, draft_id: str, action: str) -> AuditRow | None:
        """keeps approval actions idempotent across retries."""
        ...

    def insert_audit(self, audit: AuditRow) -> AuditRow:
        """records reviewer/system decisions as immutable workflow evidence."""
        ...

    def list_emails(self) -> list[EmailRow]:
        """gives operators visibility into intake history."""
        ...

    def get_email(self, email_id: str) -> EmailRow | None:
        """lets reprocessing start from the original stored email."""
        ...

    def upsert_email(self, email: EmailRow) -> EmailRow:
        """persists status transitions from received to processed."""
        ...


class MemoryStateRepository:
    """keeps tests isolated without requiring a running PostgreSQL server."""

    def __init__(self) -> None:
        """protects shared test state from concurrent request mutations."""
        self._lock = RLock()
        self._drafts: dict[str, DraftRow] = {}
        self._audits: dict[str, AuditRow] = {}
        self._emails: dict[str, EmailRow] = {}

    def initialize(self) -> None:
        """matches the PostgreSQL repository contract even with no setup."""
        return None

    def list_drafts(self) -> list[DraftRow]:
        """returns copies so callers cannot mutate repository internals."""
        with self._lock:
            return [deepcopy(row) for row in self._drafts.values()]

    def get_draft(self, draft_id: str) -> DraftRow | None:
        """mirrors database lookup semantics for tests."""
        with self._lock:
            row = self._drafts.get(draft_id)
            return deepcopy(row) if row else None

    def find_draft(
        self, *, sender: str, subject: str, body: str, status: str
    ) -> DraftRow | None:
        """supports deduplication logic without database-specific code."""
        with self._lock:
            for row in self._drafts.values():
                if (
                    row.get("sender") == sender
                    and row.get("subject") == subject
                    and row.get("body") == body
                    and row.get("status") == status
                ):
                    return deepcopy(row)
        return None

    def upsert_draft(self, draft: DraftRow) -> DraftRow:
        """lets tests exercise create/update paths without persistence files."""
        with self._lock:
            self._drafts[str(draft["draft_id"])] = deepcopy(draft)
            return deepcopy(draft)

    def delete_draft(self, draft_id: str) -> None:
        """simulates approval cleanup in isolated tests."""
        with self._lock:
            self._drafts.pop(draft_id, None)

    def list_audits(self) -> list[AuditRow]:
        """exposes copied audit history for assertions."""
        with self._lock:
            return [deepcopy(row) for row in self._audits.values()]

    def get_audit(self, audit_id: str) -> AuditRow | None:
        """mirrors direct database audit lookup in tests."""
        with self._lock:
            row = self._audits.get(audit_id)
            return deepcopy(row) if row else None

    def find_audit(self, *, draft_id: str, action: str) -> AuditRow | None:
        """keeps retry/idempotency behavior testable without PostgreSQL."""
        with self._lock:
            for row in self._audits.values():
                if row.get("draft_id") == draft_id and row.get("action") == action:
                    return deepcopy(row)
        return None

    def insert_audit(self, audit: AuditRow) -> AuditRow:
        """assigns IDs consistently when tests omit them."""
        row = deepcopy(audit)
        row.setdefault("audit_id", f"AUD-{uuid4().hex[:8].upper()}")
        with self._lock:
            self._audits[str(row["audit_id"])] = row
            return deepcopy(row)

    def list_emails(self) -> list[EmailRow]:
        """lets email queue tests inspect stored intake records."""
        with self._lock:
            return [deepcopy(row) for row in self._emails.values()]

    def get_email(self, email_id: str) -> EmailRow | None:
        """supports reprocess tests with the same lookup path as production."""
        with self._lock:
            row = self._emails.get(email_id)
            return deepcopy(row) if row else None

    def upsert_email(self, email: EmailRow) -> EmailRow:
        """stores intake status changes without leaking mutable references."""
        with self._lock:
            self._emails[str(email["email_id"])] = deepcopy(email)
            return deepcopy(email)


class PostgresStateRepository:
    """makes the app process stateless by storing workflow objects in PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        """keeps connection configuration explicit and environment-driven."""
        self.database_url = database_url

    def initialize(self) -> None:
        """bootstraps tables so Docker startup does not need a manual migration."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_drafts (
                    draft_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    revisions INTEGER NOT NULL DEFAULT 0,
                    last_rejection_reason TEXT NOT NULL DEFAULT '',
                    ai_draft_text TEXT NOT NULL DEFAULT '',
                    workflow JSONB
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS swift_drafts_review_idx
                    ON swift_drafts (status, created DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_audits (
                    audit_id TEXT PRIMARY KEY,
                    draft_id TEXT,
                    action TEXT,
                    timestamp TEXT,
                    payload JSONB NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS swift_audits_action_idx
                    ON swift_audits (action, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_emails (
                    email_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    raw_body TEXT,
                    preprocessed BOOLEAN NOT NULL DEFAULT FALSE,
                    removed_line_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    draft_id TEXT,
                    payload JSONB NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS swift_emails_created_idx
                    ON swift_emails (created_at DESC)
                """
            )

    def list_drafts(self) -> list[DraftRow]:
        """feeds pending-review views from durable storage."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM swift_drafts ORDER BY created DESC"
            ).fetchall()
        return [self._draft_from_row(row) for row in rows]

    def get_draft(self, draft_id: str) -> DraftRow | None:
        """lets approval/rejection act on a durable draft row."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM swift_drafts WHERE draft_id = %s", (draft_id,)
            ).fetchone()
        return self._draft_from_row(row) if row else None

    def find_draft(
        self, *, sender: str, subject: str, body: str, status: str
    ) -> DraftRow | None:
        """avoids duplicate pending drafts when the same email is retried."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM swift_drafts
                WHERE sender = %s AND subject = %s AND body = %s AND status = %s
                ORDER BY updated DESC
                LIMIT 1
                """,
                (sender, subject, body, status),
            ).fetchone()
        return self._draft_from_row(row) if row else None

    def upsert_draft(self, draft: DraftRow) -> DraftRow:
        """handles new drafts and regenerated versions through one write path."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO swift_drafts (
                    draft_id, sender, subject, body, status, created, updated,
                    revisions, last_rejection_reason, ai_draft_text, workflow
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (draft_id) DO UPDATE SET
                    sender = EXCLUDED.sender,
                    subject = EXCLUDED.subject,
                    body = EXCLUDED.body,
                    status = EXCLUDED.status,
                    created = EXCLUDED.created,
                    updated = EXCLUDED.updated,
                    revisions = EXCLUDED.revisions,
                    last_rejection_reason = EXCLUDED.last_rejection_reason,
                    ai_draft_text = EXCLUDED.ai_draft_text,
                    workflow = EXCLUDED.workflow
                """,
                (
                    draft["draft_id"],
                    draft["sender"],
                    draft["subject"],
                    draft["body"],
                    draft["status"],
                    draft["created"],
                    draft["updated"],
                    int(draft.get("revisions", 0)),
                    draft.get("last_rejection_reason", ""),
                    draft.get("ai_draft_text", ""),
                    self._json(draft.get("workflow")),
                ),
            )
        return dict(draft)

    def delete_draft(self, draft_id: str) -> None:
        """approved drafts should leave the active review table."""
        with self._connect() as conn:
            conn.execute("DELETE FROM swift_drafts WHERE draft_id = %s", (draft_id,))

    def list_audits(self) -> list[AuditRow]:
        """returns JSON payloads in decision-time order for audit screens."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM swift_audits ORDER BY timestamp DESC NULLS LAST"
            ).fetchall()
        return [dict(row["payload"]) for row in rows]

    def get_audit(self, audit_id: str) -> AuditRow | None:
        """retrieves the original decision payload without column loss."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM swift_audits WHERE audit_id = %s", (audit_id,)
            ).fetchone()
        return dict(row["payload"]) if row else None

    def find_audit(self, *, draft_id: str, action: str) -> AuditRow | None:
        """makes repeated approval requests return the original audit."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload FROM swift_audits
                WHERE draft_id = %s AND action = %s
                ORDER BY timestamp DESC NULLS LAST
                LIMIT 1
                """,
                (draft_id, action),
            ).fetchone()
        return dict(row["payload"]) if row else None

    def insert_audit(self, audit: AuditRow) -> AuditRow:
        """stores flexible audit details while indexing common lookup fields."""
        row = dict(audit)
        row.setdefault("audit_id", f"AUD-{uuid4().hex[:8].upper()}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO swift_audits (audit_id, draft_id, action, timestamp, payload)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (audit_id) DO UPDATE SET
                    draft_id = EXCLUDED.draft_id,
                    action = EXCLUDED.action,
                    timestamp = EXCLUDED.timestamp,
                    payload = EXCLUDED.payload
                """,
                (
                    row["audit_id"],
                    row.get("draft_id") or row.get("target_id"),
                    row.get("action"),
                    row.get("timestamp") or row.get("created_at"),
                    self._json(row),
                ),
            )
        return row

    def list_emails(self) -> list[EmailRow]:
        """shows intake history using the stored canonical payload."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM swift_emails ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row["payload"]) for row in rows]

    def get_email(self, email_id: str) -> EmailRow | None:
        """retrieves the exact stored email for reprocessing."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM swift_emails WHERE email_id = %s", (email_id,)
            ).fetchone()
        return dict(row["payload"]) if row else None

    def upsert_email(self, email: EmailRow) -> EmailRow:
        """persists receipt, processing, and draft linkage transitions."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO swift_emails (
                    email_id, sender, subject, body, raw_body, preprocessed,
                    removed_line_count, status, created_at, updated_at, draft_id, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email_id) DO UPDATE SET
                    sender = EXCLUDED.sender,
                    subject = EXCLUDED.subject,
                    body = EXCLUDED.body,
                    raw_body = EXCLUDED.raw_body,
                    preprocessed = EXCLUDED.preprocessed,
                    removed_line_count = EXCLUDED.removed_line_count,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    draft_id = EXCLUDED.draft_id,
                    payload = EXCLUDED.payload
                """,
                (
                    email["email_id"],
                    email["sender"],
                    email["subject"],
                    email["body"],
                    email.get("raw_body"),
                    bool(email.get("preprocessed", False)),
                    int(email.get("removed_line_count", 0)),
                    email["status"],
                    email["created_at"],
                    email.get("updated_at"),
                    email.get("draft_id"),
                    self._json(email),
                ),
            )
        return dict(email)

    def _connect(self):
        """lazily imports psycopg so test-memory mode has fewer dependencies."""
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL storage requires psycopg. Install dependencies from "
                "requirements.txt or run with SWIFT_STORAGE_BACKEND=memory for tests."
            ) from exc

        return psycopg.connect(self.database_url, autocommit=True, row_factory=dict_row)

    @staticmethod
    def _json(value: Any):
        """tells psycopg to encode Python dict/list values as JSONB."""
        from psycopg.types.json import Jsonb

        return Jsonb(value)

    @staticmethod
    def _draft_from_row(row: dict[str, Any]) -> DraftRow:
        """normalizes database rows to the service-layer draft shape."""
        return {
            "draft_id": row["draft_id"],
            "sender": row["sender"],
            "subject": row["subject"],
            "body": row["body"],
            "status": row["status"],
            "created": row["created"],
            "updated": row["updated"],
            "revisions": row.get("revisions", 0),
            "last_rejection_reason": row.get("last_rejection_reason", ""),
            "ai_draft_text": row.get("ai_draft_text", ""),
            "workflow": row.get("workflow"),
        }


_repository: StateRepository | None = None


def get_state_repository() -> StateRepository:
    """shares one repository instance so all services use the same backend."""
    global _repository
    if _repository is None:
        _repository = _build_repository()
        _repository.initialize()
    return _repository


def _build_repository() -> StateRepository:
    """selects storage from one plug-and-play settings object."""
    settings = get_app_settings()
    backend = settings.storage_mode
    database_url = settings.database_url

    if backend == "memory":
        return MemoryStateRepository()

    if backend != "postgres":
        raise ValueError(f"Unsupported SWIFT_STORAGE_BACKEND: {backend}")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is required for PostgreSQL storage. "
            "Omit SWIFT_STORAGE_BACKEND or set it to memory for zero-config startup."
        )

    return PostgresStateRepository(database_url)
