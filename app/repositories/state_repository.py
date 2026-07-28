from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from app.core.config import get_app_settings

try:
    psycopg = import_module("psycopg")
    dict_row = import_module("psycopg.rows").dict_row
    Jsonb = import_module("psycopg.types.json").Jsonb
except ImportError as exc:  # pragma: no cover - depends on optional runtime install
    psycopg = None
    dict_row = None
    Jsonb = None
    _PSYCOPG_IMPORT_ERROR = exc
else:
    _PSYCOPG_IMPORT_ERROR = None


DraftRow = dict[str, Any]
AuditRow = dict[str, Any]
EmailRow = dict[str, Any]
UserRow = dict[str, Any]
ThreadRow = dict[str, Any]
ThreadMessageRow = dict[str, Any]
SettingRow = dict[str, Any]


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

    def list_users(self) -> list[UserRow]:
        """lists application users available for reviewer login."""
        ...

    def get_user_by_username(self, username: str) -> UserRow | None:
        """finds a login user by normalised username."""
        ...

    def upsert_user(self, user: UserRow) -> UserRow:
        """creates or updates a login user with a stored password hash."""
        ...

    def find_thread(self, *, sender: str, subject: str) -> ThreadRow | None:
        """finds an email thread by normalised sender and subject."""
        ...

    def upsert_thread(self, thread: ThreadRow) -> ThreadRow:
        """creates or updates a normalised email thread."""
        ...

    def list_thread_messages(self, thread_id: str) -> list[ThreadMessageRow]:
        """lists normalised messages for one email thread."""
        ...

    def insert_thread_message(
        self, message: ThreadMessageRow
    ) -> ThreadMessageRow:
        """stores one normalised email-thread message."""
        ...

    def get_setting(self, key: str) -> SettingRow | None:
        """retrieves one stored application setting by key."""
        ...

    def upsert_setting(self, setting: SettingRow) -> SettingRow:
        """creates or updates a stored application setting."""
        ...

    def delete_setting(self, key: str) -> None:
        """removes one stored application setting."""
        ...


class MemoryStateRepository:
    """keeps tests isolated without requiring a running PostgreSQL server."""

    def __init__(self) -> None:
        """protects shared test state from concurrent request mutations."""
        self._lock = RLock()
        self._drafts: dict[str, DraftRow] = {}
        self._audits: dict[str, AuditRow] = {}
        self._emails: dict[str, EmailRow] = {}
        self._users: dict[str, UserRow] = {}
        self._threads: dict[str, ThreadRow] = {}
        self._thread_messages: dict[str, ThreadMessageRow] = {}
        self._settings: dict[str, SettingRow] = {}

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
        """keeps retry/idempotency behaviour testable without PostgreSQL."""
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
            stored = deepcopy(row)
        self._record_audit_thread_messages(stored)
        return stored

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
            row = deepcopy(email)
        self._record_email_thread_message(row)
        return row

    def list_users(self) -> list[UserRow]:
        """returns copied user rows for auth UI/account assertions."""
        with self._lock:
            return [deepcopy(row) for row in self._users.values()]

    def get_user_by_username(self, username: str) -> UserRow | None:
        """performs case-insensitive username lookup like PostgreSQL."""
        normalised_username = (username or "").strip().lower()
        with self._lock:
            row = self._users.get(normalised_username)
            return deepcopy(row) if row else None

    def upsert_user(self, user: UserRow) -> UserRow:
        """stores login users with the same copy boundary as other rows."""
        row = deepcopy(user)
        row["username"] = str(row["username"]).strip().lower()
        with self._lock:
            self._users[str(row["username"])] = row
            return deepcopy(row)

    def find_thread(self, *, sender: str, subject: str) -> ThreadRow | None:
        """finds an existing thread using the same key as PostgreSQL."""
        sender_key = _normalize_email_address(sender)
        subject_key = _thread_subject_key(subject)
        with self._lock:
            for row in self._threads.values():
                if (
                    row.get("sender_key") == sender_key
                    and row.get("subject_key") == subject_key
                ):
                    return deepcopy(row)
        return None

    def upsert_thread(self, thread: ThreadRow) -> ThreadRow:
        """creates or updates a normalised thread row."""
        row = deepcopy(thread)
        row.setdefault("thread_id", f"THR-{uuid4().hex[:8].upper()}")
        row["sender_key"] = _normalize_email_address(str(row.get("sender") or ""))
        row["subject_key"] = _thread_subject_key(str(row.get("subject") or ""))
        with self._lock:
            existing = self.find_thread(
                sender=str(row.get("sender") or ""),
                subject=str(row.get("subject") or ""),
            )
            if existing:
                row["thread_id"] = existing["thread_id"]
                row.setdefault("created_at", existing.get("created_at"))
            self._threads[str(row["thread_id"])] = row
            return deepcopy(row)

    def list_thread_messages(self, thread_id: str) -> list[ThreadMessageRow]:
        """returns copied messages for one normalised email thread."""
        with self._lock:
            rows = [
                deepcopy(row)
                for row in self._thread_messages.values()
                if row.get("thread_id") == thread_id
            ]
        return sorted(rows, key=lambda row: str(row.get("timestamp") or ""))

    def insert_thread_message(
        self, message: ThreadMessageRow
    ) -> ThreadMessageRow:
        """stores a thread message idempotently."""
        row = deepcopy(message)
        row.setdefault("message_id", f"MSG-{uuid4().hex[:8].upper()}")
        with self._lock:
            self._thread_messages[str(row["message_id"])] = row
            return deepcopy(row)

    def _record_email_thread_message(self, email: EmailRow) -> None:
        """normalises inbound email rows into the thread message store."""
        body = str(email.get("body") or "").strip()
        if not body:
            return
        thread = _thread_for_message(
            self,
            sender=str(email.get("sender") or ""),
            subject=str(email.get("subject") or ""),
            timestamp=str(email.get("created_at") or email.get("updated_at") or ""),
        )
        self.insert_thread_message(
            _thread_message_from_email(thread["thread_id"], email)
        )

    def _record_audit_thread_messages(self, audit: AuditRow) -> None:
        """normalises audit rows into customer and officer thread messages."""
        for message in _thread_messages_from_audit(self, audit):
            self.insert_thread_message(message)

    def get_setting(self, key: str) -> SettingRow | None:
        """retrieves one copied setting row."""
        with self._lock:
            row = self._settings.get(key)
            return deepcopy(row) if row else None

    def upsert_setting(self, setting: SettingRow) -> SettingRow:
        """stores one setting row in memory."""
        row = deepcopy(setting)
        with self._lock:
            self._settings[str(row["key"])] = row
            return deepcopy(row)

    def delete_setting(self, key: str) -> None:
        """removes one memory setting row."""
        with self._lock:
            self._settings.pop(key, None)


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
                CREATE TABLE IF NOT EXISTS swift_users (
                    username TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    hashed_password TEXT NOT NULL,
                    level TEXT NOT NULL CHECK (
                        level IN ('sales officer', 'admin', 'sales manager')
                    ),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE swift_users
                    DROP CONSTRAINT IF EXISTS swift_users_level_check
                """
            )
            conn.execute(
                """
                UPDATE swift_users
                SET level = 'sales officer'
                WHERE level = 'sales person'
                """
            )
            conn.execute(
                """
                ALTER TABLE swift_users
                    ADD CONSTRAINT swift_users_level_check
                    CHECK (level IN ('sales officer', 'admin', 'sales manager'))
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_audits (
                    audit_id TEXT PRIMARY KEY,
                    draft_id TEXT,
                    action TEXT,
                    timestamp TEXT,
                    approver_username TEXT REFERENCES swift_users(username),
                    payload JSONB NOT NULL
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE swift_audits
                    ADD COLUMN IF NOT EXISTS approver_username TEXT
                    REFERENCES swift_users(username)
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_products (
                    product_id TEXT PRIMARY KEY,
                    sku TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT 'https://safetyware.com/products/',
                    category TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT 'RM',
                    unit_price NUMERIC(10,2) NOT NULL,
                    stock_availability INTEGER NOT NULL DEFAULT 0,
                    unit_of_measure TEXT NOT NULL DEFAULT 'unit',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE swift_products
                    ADD COLUMN IF NOT EXISTS source_url TEXT
                    NOT NULL DEFAULT 'https://safetyware.com/products/'
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS swift_products_status_idx
                    ON swift_products (status, name)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_threads (
                    thread_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    sender_key TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (sender_key, subject_key)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS swift_threads_updated_idx
                    ON swift_threads (updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_thread_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES swift_threads(thread_id)
                        ON DELETE CASCADE,
                    source_type TEXT NOT NULL CHECK (source_type IN ('email', 'audit')),
                    source_id TEXT NOT NULL,
                    version_id TEXT,
                    kind TEXT NOT NULL CHECK (kind IN ('customer', 'officer')),
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    action TEXT,
                    approver TEXT,
                    approver_username TEXT REFERENCES swift_users(username),
                    emailed_to TEXT,
                    sent BOOLEAN NOT NULL DEFAULT FALSE,
                    review_comment TEXT,
                    payload JSONB NOT NULL
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE swift_thread_messages
                    ADD COLUMN IF NOT EXISTS source_type TEXT
                    CHECK (source_type IN ('email', 'audit'))
                """
            )
            conn.execute(
                """
                ALTER TABLE swift_thread_messages
                    ADD COLUMN IF NOT EXISTS source_id TEXT
                """
            )
            conn.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'swift_thread_messages'
                            AND column_name = 'email_id'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'swift_thread_messages'
                            AND column_name = 'audit_id'
                    ) THEN
                        UPDATE swift_thread_messages
                        SET
                            source_type = CASE
                                WHEN source_type IS NOT NULL THEN source_type
                                WHEN email_id IS NOT NULL THEN 'email'
                                WHEN audit_id IS NOT NULL THEN 'audit'
                                ELSE source_type
                            END,
                            source_id = COALESCE(source_id, email_id, audit_id)
                        WHERE source_type IS NULL OR source_id IS NULL;
                    END IF;
                END $$;
                """
            )
            conn.execute(
                """
                ALTER TABLE swift_thread_messages
                    ADD COLUMN IF NOT EXISTS approver_username TEXT
                    REFERENCES swift_users(username)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS swift_thread_messages_thread_idx
                    ON swift_thread_messages (thread_id, timestamp)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swift_settings (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS swift_users_level_idx
                    ON swift_users (level, username)
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
                INSERT INTO swift_audits (
                    audit_id, draft_id, action, timestamp, approver_username, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (audit_id) DO UPDATE SET
                    draft_id = EXCLUDED.draft_id,
                    action = EXCLUDED.action,
                    timestamp = EXCLUDED.timestamp,
                    approver_username = EXCLUDED.approver_username,
                    payload = EXCLUDED.payload
                """,
                (
                    row["audit_id"],
                    row.get("draft_id") or row.get("target_id"),
                    row.get("action"),
                    row.get("timestamp") or row.get("created_at"),
                    row.get("approver_username"),
                    self._json(row),
                ),
            )
        self._record_audit_thread_messages(row)
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
        self._record_email_thread_message(dict(email))
        return dict(email)

    def list_users(self) -> list[UserRow]:
        """lists login user rows in a stable order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT username, email, hashed_password, level
                FROM swift_users
                ORDER BY username
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user_by_username(self, username: str) -> UserRow | None:
        """retrieves the login row used by the auth service."""
        normalised_username = (username or "").strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT username, email, hashed_password, level
                FROM swift_users
                WHERE lower(username) = %s
                """,
                (normalised_username,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_user(self, user: UserRow) -> UserRow:
        """creates or updates a user row while preserving hashed credentials."""
        row = dict(user)
        row["username"] = str(row["username"]).strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO swift_users (username, email, hashed_password, level)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    email = EXCLUDED.email,
                    hashed_password = EXCLUDED.hashed_password,
                    level = EXCLUDED.level,
                    updated_at = now()
                """,
                (
                    row["username"],
                    row["email"],
                    row["hashed_password"],
                    row["level"],
                ),
            )
        return row

    def find_thread(self, *, sender: str, subject: str) -> ThreadRow | None:
        """finds an existing normalised thread by sender and subject."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM swift_threads
                WHERE sender_key = %s AND subject_key = %s
                """,
                (_normalize_email_address(sender), _thread_subject_key(subject)),
            ).fetchone()
        return dict(row) if row else None

    def upsert_thread(self, thread: ThreadRow) -> ThreadRow:
        """creates or updates a normalised thread row."""
        row = dict(thread)
        row.setdefault("thread_id", f"THR-{uuid4().hex[:8].upper()}")
        row["sender_key"] = _normalize_email_address(str(row.get("sender") or ""))
        row["subject_key"] = _thread_subject_key(str(row.get("subject") or ""))
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM swift_threads
                WHERE sender_key = %s AND subject_key = %s
                """,
                (row["sender_key"], row["subject_key"]),
            ).fetchone()
            if existing:
                row["thread_id"] = existing["thread_id"]
                row.setdefault("created_at", existing["created_at"])
            conn.execute(
                """
                INSERT INTO swift_threads (
                    thread_id, sender, sender_key, subject, subject_key,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sender_key, subject_key) DO UPDATE SET
                    sender = EXCLUDED.sender,
                    subject = EXCLUDED.subject,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    row["thread_id"],
                    row["sender"],
                    row["sender_key"],
                    row["subject"],
                    row["subject_key"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        return row

    def list_thread_messages(self, thread_id: str) -> list[ThreadMessageRow]:
        """returns normalised messages for one thread."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM swift_thread_messages
                WHERE thread_id = %s
                ORDER BY timestamp
                """,
                (thread_id,),
            ).fetchall()
        return [dict(row["payload"]) for row in rows]

    def insert_thread_message(
        self, message: ThreadMessageRow
    ) -> ThreadMessageRow:
        """stores a normalised thread message idempotently."""
        row = dict(message)
        row.setdefault("message_id", f"MSG-{uuid4().hex[:8].upper()}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO swift_thread_messages (
                    message_id, thread_id, source_type, source_id, version_id,
                    kind, sender, subject, body, timestamp, action, approver,
                    approver_username, emailed_to, sent, review_comment, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO UPDATE SET
                    source_type = EXCLUDED.source_type,
                    source_id = EXCLUDED.source_id,
                    version_id = EXCLUDED.version_id,
                    body = EXCLUDED.body,
                    timestamp = EXCLUDED.timestamp,
                    action = EXCLUDED.action,
                    approver = EXCLUDED.approver,
                    approver_username = EXCLUDED.approver_username,
                    emailed_to = EXCLUDED.emailed_to,
                    sent = EXCLUDED.sent,
                    review_comment = EXCLUDED.review_comment,
                    payload = EXCLUDED.payload
                """,
                (
                    row["message_id"],
                    row["thread_id"],
                    row["source_type"],
                    row["source_id"],
                    row.get("version_id"),
                    row["kind"],
                    row["sender"],
                    row["subject"],
                    row["body"],
                    row["timestamp"],
                    row.get("action"),
                    row.get("approver"),
                    row.get("approver_username"),
                    row.get("emailed_to"),
                    bool(row.get("sent", False)),
                    row.get("review_comment"),
                    self._json(row),
                ),
            )
        return row

    def _record_email_thread_message(self, email: EmailRow) -> None:
        """normalises inbound email rows into the thread message store."""
        body = str(email.get("body") or "").strip()
        if not body:
            return
        thread = _thread_for_message(
            self,
            sender=str(email.get("sender") or ""),
            subject=str(email.get("subject") or ""),
            timestamp=str(email.get("created_at") or email.get("updated_at") or ""),
        )
        self.insert_thread_message(
            _thread_message_from_email(thread["thread_id"], email)
        )

    def _record_audit_thread_messages(self, audit: AuditRow) -> None:
        """normalises audit rows into customer and officer thread messages."""
        for message in _thread_messages_from_audit(self, audit):
            self.insert_thread_message(message)

    def get_setting(self, key: str) -> SettingRow | None:
        """retrieves one stored application setting."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT key, value, updated_at FROM swift_settings WHERE key = %s",
                (key,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_setting(self, setting: SettingRow) -> SettingRow:
        """creates or updates one stored application setting."""
        row = dict(setting)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO swift_settings (key, value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at
                """,
                (row["key"], self._json(row.get("value")), row["updated_at"]),
            )
        return row

    def delete_setting(self, key: str) -> None:
        """removes one stored application setting."""
        with self._connect() as conn:
            conn.execute("DELETE FROM swift_settings WHERE key = %s", (key,))

    def _connect(self):
        """opens the configured PostgreSQL connection."""
        psycopg_module, row_factory = _postgres_connection_parts()

        return psycopg_module.connect(
            self.database_url,
            autocommit=True,
            row_factory=row_factory,
        )

    @staticmethod
    def _json(value: Any):
        """tells psycopg to encode Python dict/list values as JSONB."""
        jsonb = _postgres_jsonb_encoder()
        return jsonb(value)

    @staticmethod
    def _draft_from_row(row: dict[str, Any]) -> DraftRow:
        """normalises database rows to the service-layer draft shape."""
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


def _thread_for_message(
    repository: StateRepository,
    *,
    sender: str,
    subject: str,
    timestamp: str,
) -> ThreadRow:
    """finds or creates the normalised thread for a message."""
    existing = repository.find_thread(sender=sender, subject=subject)
    now = timestamp or ""
    return repository.upsert_thread(
        {
            "thread_id": existing.get("thread_id") if existing else f"THR-{uuid4().hex[:8].upper()}",
            "sender": sender,
            "subject": subject,
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
    )


def _thread_message_from_email(
    thread_id: str,
    email: EmailRow,
) -> ThreadMessageRow:
    """converts a stored email row into a normalised customer message."""
    email_id = str(email.get("email_id") or f"EML-{uuid4().hex[:8].upper()}")
    return {
        "message_id": f"{email_id}-customer",
        "thread_id": thread_id,
        "source_type": "email",
        "source_id": email_id,
        "version_id": None,
        "kind": "customer",
        "sender": str(email.get("sender") or ""),
        "subject": str(email.get("subject") or ""),
        "body": str(email.get("body") or ""),
        "timestamp": str(email.get("created_at") or email.get("updated_at") or ""),
        "action": None,
        "approver": None,
        "approver_username": None,
        "emailed_to": None,
        "sent": False,
        "review_comment": None,
    }


def _thread_messages_from_audit(
    repository: StateRepository,
    audit: AuditRow,
) -> list[ThreadMessageRow]:
    """converts audit payloads into normalised customer and officer messages."""
    action = str(audit.get("action") or "").lower()
    if action not in {"approved", "edited", "rejected"}:
        return []

    sender = str(audit.get("sender") or "")
    subject = str(audit.get("subject") or "")
    timestamp = str(audit.get("timestamp") or audit.get("created_at") or "")
    thread = _thread_for_message(
        repository,
        sender=sender,
        subject=subject,
        timestamp=timestamp,
    )
    thread_id = thread["thread_id"]
    audit_id = str(audit.get("audit_id") or f"AUD-{uuid4().hex[:8].upper()}")
    messages: list[ThreadMessageRow] = []
    customer_text = str(audit.get("customer_inquiry") or "").strip()
    if customer_text:
        messages.append(
            {
                "message_id": f"{audit_id}-customer",
                "thread_id": thread_id,
                "source_type": "audit",
                "source_id": audit_id,
                "version_id": audit.get("version_id"),
                "kind": "customer",
                "sender": sender,
                "subject": subject,
                "body": customer_text,
                "timestamp": timestamp,
                "action": action,
                "approver": audit.get("approver"),
                "approver_username": audit.get("approver_username"),
                "emailed_to": audit.get("emailed_to"),
                "sent": bool(audit.get("sent", False)),
                "review_comment": None,
            }
        )

    officer_text = str(audit.get("ai_draft") or audit.get("review_comment") or "").strip()
    if officer_text:
        approver = str(audit.get("approver") or "Sales Officer")
        messages.append(
            {
                "message_id": f"{audit_id}-officer",
                "thread_id": thread_id,
                "source_type": "audit",
                "source_id": audit_id,
                "version_id": audit.get("version_id"),
                "kind": "officer",
                "sender": approver,
                "subject": f"Re: {subject}".strip(),
                "body": officer_text,
                "timestamp": timestamp,
                "action": action,
                "approver": approver,
                "approver_username": audit.get("approver_username"),
                "emailed_to": audit.get("emailed_to"),
                "sent": bool(audit.get("sent", False)),
                "review_comment": audit.get("review_comment"),
            }
        )
    return messages


def _normalize_email_address(value: str) -> str:
    """compares bare email addresses even when display names are present."""
    import re

    match = re.search(r"<([^>]+)>", value)
    address = match.group(1) if match else value
    return address.strip().lower()


def _thread_subject_key(subject: str) -> str:
    """normalises reply/forward subjects to one conversation key."""
    import re

    text = " ".join((subject or "No subject").split())
    text = re.sub(r"\s+\(Regenerated v\d+\)$", "", text, flags=re.IGNORECASE)
    prefix_re = re.compile(r"^(?:(?:re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
    previous = None
    while previous != text:
        previous = text
        text = prefix_re.sub("", text).strip()
    return text.lower()


def _postgres_connection_parts() -> tuple[Any, Any]:
    """returns concrete psycopg connection helpers before database use."""
    if psycopg is not None and dict_row is not None:
        return psycopg, dict_row
    raise RuntimeError(
        "PostgreSQL storage requires psycopg. Install dependencies from "
        "requirements.txt or run with SWIFT_STORAGE_BACKEND=memory for tests."
    ) from _psycopg_import_error()


def _postgres_jsonb_encoder() -> Any:
    """returns the concrete JSONB encoder before payload serialization."""
    if Jsonb is not None:
        return Jsonb
    raise RuntimeError(
        "PostgreSQL JSONB encoding requires psycopg. Install dependencies "
        "from requirements.txt or run with SWIFT_STORAGE_BACKEND=memory for tests."
    ) from _psycopg_import_error()


def _psycopg_import_error() -> Exception:
    """returns the captured psycopg import failure as a concrete exception."""
    if _PSYCOPG_IMPORT_ERROR is not None:
        return _PSYCOPG_IMPORT_ERROR
    return RuntimeError("psycopg module is unavailable.")


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
