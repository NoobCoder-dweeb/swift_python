from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4

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

    def get_user_by_id(self, user_id: str) -> UserRow | None:
        """finds a user by immutable UUID identity."""
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

    def insert_thread_message(self, message: ThreadMessageRow) -> ThreadMessageRow:
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
            row = next(
                (
                    item
                    for item in self._users.values()
                    if str(item.get("username") or "").lower() == normalised_username
                ),
                None,
            )
            return deepcopy(row) if row else None

    def get_user_by_id(self, user_id: str) -> UserRow | None:
        """retrieves a user without depending on a mutable login name."""
        with self._lock:
            row = self._users.get(str(user_id))
            return deepcopy(row) if row else None

    def upsert_user(self, user: UserRow) -> UserRow:
        """stores login users with the same copy boundary as other rows."""
        row = deepcopy(user)
        row["username"] = str(row["username"]).strip().lower()
        with self._lock:
            existing = next(
                (
                    item
                    for item in self._users.values()
                    if item.get("username") == row["username"]
                ),
                None,
            )
            row.setdefault(
                "user_id", existing.get("user_id") if existing else str(uuid4())
            )
            self._users[str(row["user_id"])] = row
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

    def insert_thread_message(self, message: ThreadMessageRow) -> ThreadMessageRow:
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
            if message.get("kind") == "customer" and _message_already_stored(
                self, message
            ):
                continue
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
        """creates the canonical schema and upgrades the legacy projection schema."""
        with self._connect() as conn:
            legacy = conn.execute(
                "SELECT to_regclass('public.swift_thread_messages') IS NOT NULL AS present"
            ).fetchone()
            schema_dir = Path(__file__).resolve().parent
            if legacy and legacy["present"]:
                migration = (
                    schema_dir / "migrations" / "001_normalize_messages_and_users.sql"
                )
                with conn.transaction():
                    conn.execute(migration.read_text(encoding="utf-8"))
            legacy_links = conn.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'swift_messages'
                      AND column_name IN ('draft_id', 'email_id')
                    UNION ALL
                    SELECT 1 FROM pg_constraint
                    WHERE conname LIKE 'swift_thread_messages_%'
                ) AS present
                """
            ).fetchone()
            if legacy_links and legacy_links["present"]:
                migration = (
                    schema_dir / "migrations" / "002_remove_legacy_message_links.sql"
                )
                with conn.transaction():
                    conn.execute(migration.read_text(encoding="utf-8"))
            with conn.transaction():
                conn.execute((schema_dir / "schema.sql").read_text(encoding="utf-8"))
                migration = (
                    schema_dir / "migrations" / "003_add_round_pedal_bin.sql"
                )
                if migration.exists():
                    conn.execute(migration.read_text(encoding="utf-8"))

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
                "SELECT payload FROM swift_audits ORDER BY occurred_at DESC NULLS LAST"
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
                ORDER BY occurred_at DESC NULLS LAST
                LIMIT 1
                """,
                (draft_id, action),
            ).fetchone()
        return dict(row["payload"]) if row else None

    def insert_audit(self, audit: AuditRow) -> AuditRow:
        """stores flexible audit details while indexing common lookup fields."""
        row = dict(audit)
        row.setdefault("audit_id", f"AUD-{uuid4().hex[:8].upper()}")
        row["approver_user_id"] = self._resolve_user_id(
            row.get("approver_user_id"), row.get("approver_username")
        )
        with self._connect() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO swift_audits (
                    audit_id, draft_id, action, occurred_at, approver_user_id, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (audit_id) DO UPDATE SET
                    draft_id = EXCLUDED.draft_id,
                    action = EXCLUDED.action,
                    occurred_at = EXCLUDED.occurred_at,
                    approver_user_id = EXCLUDED.approver_user_id,
                    payload = EXCLUDED.payload
                """,
                (
                    row["audit_id"],
                    row.get("draft_id") or row.get("target_id"),
                    row.get("action"),
                    row.get("timestamp") or row.get("created_at"),
                    row.get("approver_user_id"),
                    self._json(row),
                ),
            )
            action = str(row.get("action") or "").lower()
            if action in {"approved", "edited", "rejected"}:
                thread = self._upsert_thread_on_connection(
                    conn,
                    sender=str(row.get("sender") or ""),
                    subject=str(row.get("subject") or ""),
                    timestamp=str(row.get("timestamp") or row.get("created_at") or ""),
                )
                for message in _thread_messages_for_thread(thread["thread_id"], row):
                    if (
                        message.get("kind") == "customer"
                        and conn.execute(
                            """
                        SELECT EXISTS (
                            SELECT 1 FROM swift_messages
                            WHERE thread_id = %s AND kind = 'customer'
                              AND sender = %s AND body = %s
                        ) AS present
                        """,
                            (message["thread_id"], message["sender"], message["body"]),
                        ).fetchone()["present"]
                    ):
                        continue
                    self._insert_message_on_connection(conn, message)
        return row

    def list_emails(self) -> list[EmailRow]:
        """joins email metadata to its canonical message content."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.*, m.sender, m.subject, m.body
                FROM swift_emails e
                JOIN swift_messages m ON m.message_id = e.message_id
                ORDER BY e.created_at DESC
                """
            ).fetchall()
        return [self._email_from_row(row) for row in rows]

    def get_email(self, email_id: str) -> EmailRow | None:
        """retrieves email metadata together with canonical message content."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT e.*, m.sender, m.subject, m.body
                FROM swift_emails e
                JOIN swift_messages m ON m.message_id = e.message_id
                WHERE e.email_id = %s
                """,
                (email_id,),
            ).fetchone()
        return self._email_from_row(row) if row else None

    def upsert_email(self, email: EmailRow) -> EmailRow:
        """persists receipt, processing, and draft linkage transitions."""
        body = str(email.get("body") or "").strip()
        if not body:
            raise ValueError("email body is required for canonical message storage")
        with self._connect() as conn, conn.transaction():
            thread = self._upsert_thread_on_connection(
                conn,
                sender=str(email.get("sender") or ""),
                subject=str(email.get("subject") or ""),
                timestamp=str(email.get("created_at") or email.get("updated_at") or ""),
            )
            message = _thread_message_from_email(thread["thread_id"], email)
            self._insert_message_on_connection(conn, message)
            conn.execute(
                """
                INSERT INTO swift_emails (
                    email_id, message_id, raw_body, preprocessed,
                    removed_line_count, status, created_at, updated_at, draft_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email_id) DO UPDATE SET
                    message_id = EXCLUDED.message_id,
                    raw_body = EXCLUDED.raw_body,
                    preprocessed = EXCLUDED.preprocessed,
                    removed_line_count = EXCLUDED.removed_line_count,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    draft_id = EXCLUDED.draft_id
                """,
                (
                    email["email_id"],
                    message["message_id"],
                    email.get("raw_body"),
                    bool(email.get("preprocessed", False)),
                    int(email.get("removed_line_count", 0)),
                    email["status"],
                    email["created_at"],
                    email.get("updated_at"),
                    email.get("draft_id"),
                ),
            )
        return dict(email)

    def list_users(self) -> list[UserRow]:
        """lists login user rows in a stable order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, username, email, hashed_password, level
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
                SELECT user_id, username, email, hashed_password, level
                FROM swift_users
                WHERE lower(username) = %s
                """,
                (normalised_username,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> UserRow | None:
        """retrieves an account by immutable UUID identity."""
        try:
            normalized_user_id = str(UUID(str(user_id or "").strip()))
        except ValueError:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_id, username, email, hashed_password, level
                FROM swift_users
                WHERE user_id = %s
                """,
                (normalized_user_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_user(self, user: UserRow) -> UserRow:
        """creates or updates a user row while preserving hashed credentials."""
        row = dict(user)
        row["username"] = str(row["username"]).strip().lower()
        existing = self.get_user_by_username(row["username"])
        row.setdefault("user_id", existing.get("user_id") if existing else str(uuid4()))
        with self._connect() as conn:
            stored = conn.execute(
                """
                INSERT INTO swift_users (user_id, username, email, hashed_password, level)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    email = EXCLUDED.email,
                    hashed_password = EXCLUDED.hashed_password,
                    level = EXCLUDED.level,
                    updated_at = now()
                RETURNING user_id, username, email, hashed_password, level
                """,
                (
                    row["user_id"],
                    row["username"],
                    row["email"],
                    row["hashed_password"],
                    row["level"],
                ),
            ).fetchone()
        return dict(stored) if stored else row

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
            return self._upsert_thread_on_connection(
                conn,
                sender=row["sender"],
                subject=row["subject"],
                timestamp=row["updated_at"],
                thread_id=row["thread_id"],
                created_at=row.get("created_at"),
            )

    def list_thread_messages(self, thread_id: str) -> list[ThreadMessageRow]:
        """returns canonical messages with source and reviewer display fields."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    m.*,
                    CASE WHEN e.email_id IS NOT NULL THEN 'email' ELSE 'audit' END AS source_type,
                    COALESCE(e.email_id, m.audit_id) AS source_id,
                    u.username AS approver_username
                FROM swift_messages m
                LEFT JOIN swift_emails e ON e.message_id = m.message_id
                LEFT JOIN swift_users u ON u.user_id = m.approver_user_id
                WHERE m.thread_id = %s
                ORDER BY m.occurred_at
                """,
                (thread_id,),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def insert_thread_message(self, message: ThreadMessageRow) -> ThreadMessageRow:
        """stores a normalised thread message idempotently."""
        row = dict(message)
        row.setdefault("message_id", f"MSG-{uuid4().hex[:8].upper()}")
        row["approver_user_id"] = self._resolve_user_id(
            row.get("approver_user_id"), row.get("approver_username")
        )
        with self._connect() as conn:
            self._insert_message_on_connection(conn, row)
        return row

    def _insert_message_on_connection(self, conn: Any, row: ThreadMessageRow) -> None:
        """writes canonical content using the caller's transaction."""
        conn.execute(
            """
                INSERT INTO swift_messages (
                    message_id, thread_id, audit_id, version_id, kind, sender,
                    subject, body, occurred_at, action, approver,
                    approver_user_id, emailed_to, sent, review_comment
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO UPDATE SET
                    thread_id = EXCLUDED.thread_id,
                    audit_id = EXCLUDED.audit_id,
                    version_id = EXCLUDED.version_id,
                    kind = EXCLUDED.kind,
                    sender = EXCLUDED.sender,
                    subject = EXCLUDED.subject,
                    body = EXCLUDED.body,
                    occurred_at = EXCLUDED.occurred_at,
                    action = EXCLUDED.action,
                    approver = EXCLUDED.approver,
                    approver_user_id = EXCLUDED.approver_user_id,
                    emailed_to = EXCLUDED.emailed_to,
                    sent = EXCLUDED.sent,
                    review_comment = EXCLUDED.review_comment
                """,
            (
                row["message_id"],
                row["thread_id"],
                row.get("source_id")
                if row.get("source_type") == "audit"
                else row.get("audit_id"),
                row.get("version_id"),
                row["kind"],
                row["sender"],
                row["subject"],
                row["body"],
                row.get("timestamp") or row.get("occurred_at"),
                row.get("action"),
                row.get("approver"),
                row.get("approver_user_id"),
                row.get("emailed_to"),
                bool(row.get("sent", False)),
                row.get("review_comment"),
            ),
        )

    def _upsert_thread_on_connection(
        self,
        conn: Any,
        *,
        sender: str,
        subject: str,
        timestamp: str,
        thread_id: str | None = None,
        created_at: Any = None,
    ) -> ThreadRow:
        """finds or creates a thread without crossing a transaction boundary."""
        sender_key = _normalize_email_address(sender)
        subject_key = _thread_subject_key(subject)
        existing = conn.execute(
            "SELECT * FROM swift_threads WHERE sender_key = %s AND subject_key = %s",
            (sender_key, subject_key),
        ).fetchone()
        if existing:
            thread_id = existing["thread_id"]
            created_at = existing["created_at"]
        stored = conn.execute(
            """
            INSERT INTO swift_threads (
                thread_id, sender, sender_key, subject, subject_key, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sender_key, subject_key) DO UPDATE SET
                sender = EXCLUDED.sender,
                subject = EXCLUDED.subject,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            (
                thread_id or f"THR-{uuid4().hex[:8].upper()}",
                sender,
                sender_key,
                subject,
                subject_key,
                created_at or timestamp,
                timestamp,
            ),
        ).fetchone()
        return dict(stored)

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

    def _resolve_user_id(self, user_id: Any, username: Any) -> str | None:
        """resolves legacy username callers to the UUID used by foreign keys."""
        if user_id:
            return str(user_id)
        if not username:
            return None
        user = self.get_user_by_username(str(username))
        return str(user["user_id"]) if user else None

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
    def _email_from_row(row: dict[str, Any]) -> EmailRow:
        """combines canonical content with email-processing metadata."""
        return {
            "email_id": row["email_id"],
            "sender": row["sender"],
            "subject": row["subject"],
            "body": row["body"],
            "raw_body": row.get("raw_body"),
            "preprocessed": bool(row.get("preprocessed", False)),
            "removed_line_count": int(row.get("removed_line_count", 0)),
            "status": row["status"],
            "created_at": _database_timestamp(row.get("created_at")),
            "updated_at": _database_timestamp(row.get("updated_at")),
            "draft_id": row.get("draft_id"),
        }

    @staticmethod
    def _message_from_row(row: dict[str, Any]) -> ThreadMessageRow:
        """adapts canonical relational rows to the repository contract."""
        return {
            "message_id": row["message_id"],
            "thread_id": row["thread_id"],
            "source_type": row.get("source_type"),
            "source_id": row.get("source_id"),
            "version_id": row.get("version_id"),
            "kind": row["kind"],
            "sender": row["sender"],
            "subject": row["subject"],
            "body": row["body"],
            "timestamp": _database_timestamp(row.get("occurred_at")),
            "action": row.get("action"),
            "approver": row.get("approver"),
            "approver_user_id": str(row["approver_user_id"])
            if row.get("approver_user_id")
            else None,
            "approver_username": row.get("approver_username"),
            "emailed_to": row.get("emailed_to"),
            "sent": bool(row.get("sent", False)),
            "review_comment": row.get("review_comment"),
        }

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
            "thread_id": existing.get("thread_id")
            if existing
            else f"THR-{uuid4().hex[:8].upper()}",
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
        "approver_user_id": None,
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
    return _thread_messages_for_thread(thread["thread_id"], audit)


def _thread_messages_for_thread(
    thread_id: str,
    audit: AuditRow,
) -> list[ThreadMessageRow]:
    """builds canonical messages once the enclosing transaction owns a thread."""
    action = str(audit.get("action") or "").lower()
    sender = str(audit.get("sender") or "")
    subject = str(audit.get("subject") or "")
    timestamp = str(audit.get("timestamp") or audit.get("created_at") or "")
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
                "approver_user_id": audit.get("approver_user_id"),
                "approver_username": audit.get("approver_username"),
                "emailed_to": audit.get("emailed_to"),
                "sent": bool(audit.get("sent", False)),
                "review_comment": None,
            }
        )

    officer_text = str(
        audit.get("ai_draft") or audit.get("review_comment") or ""
    ).strip()
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
                "approver_user_id": audit.get("approver_user_id"),
                "approver_username": audit.get("approver_username"),
                "emailed_to": audit.get("emailed_to"),
                "sent": bool(audit.get("sent", False)),
                "review_comment": audit.get("review_comment"),
            }
        )
    return messages


def _message_already_stored(
    repository: StateRepository,
    candidate: ThreadMessageRow,
) -> bool:
    """avoids copying one customer inquiry again for every audit event."""
    for stored in repository.list_thread_messages(
        str(candidate.get("thread_id") or "")
    ):
        if (
            stored.get("kind") == "customer"
            and str(stored.get("sender") or "") == str(candidate.get("sender") or "")
            and _thread_subject_key(str(stored.get("subject") or ""))
            == _thread_subject_key(str(candidate.get("subject") or ""))
            and str(stored.get("body") or "").strip()
            == str(candidate.get("body") or "").strip()
        ):
            return True
    return False


def _database_timestamp(value: Any) -> str | None:
    """keeps repository timestamps JSON-compatible after TIMESTAMPTZ migration."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


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
