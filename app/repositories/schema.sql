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
);

CREATE INDEX IF NOT EXISTS swift_drafts_review_idx
    ON swift_drafts (status, created DESC);

CREATE TABLE IF NOT EXISTS swift_users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    level TEXT NOT NULL CHECK (
        level IN ('sales officer', 'admin', 'sales manager')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS swift_users_level_idx
    ON swift_users (level, username);

CREATE TABLE IF NOT EXISTS swift_audits (
    audit_id TEXT PRIMARY KEY,
    draft_id TEXT,
    action TEXT,
    occurred_at TIMESTAMPTZ,
    approver_user_id UUID REFERENCES swift_users(user_id),
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS swift_audits_action_idx
    ON swift_audits (action, occurred_at DESC);

CREATE TABLE IF NOT EXISTS swift_threads (
    thread_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    sender_key TEXT NOT NULL,
    subject TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (sender_key, subject_key)
);

CREATE INDEX IF NOT EXISTS swift_threads_updated_idx
    ON swift_threads (updated_at DESC);

CREATE TABLE IF NOT EXISTS swift_messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES swift_threads(thread_id) ON DELETE CASCADE,
    audit_id TEXT REFERENCES swift_audits(audit_id) ON DELETE SET NULL,
    version_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('customer', 'officer')),
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    action TEXT,
    approver TEXT,
    approver_user_id UUID REFERENCES swift_users(user_id),
    emailed_to TEXT,
    sent BOOLEAN NOT NULL DEFAULT FALSE,
    review_comment TEXT,
    UNIQUE (audit_id, kind)
);

CREATE INDEX IF NOT EXISTS swift_messages_thread_idx
    ON swift_messages (thread_id, occurred_at);

CREATE TABLE IF NOT EXISTS swift_emails (
    email_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE REFERENCES swift_messages(message_id) ON DELETE CASCADE,
    raw_body TEXT,
    preprocessed BOOLEAN NOT NULL DEFAULT FALSE,
    removed_line_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ,
    draft_id TEXT
);

CREATE INDEX IF NOT EXISTS swift_emails_created_idx
    ON swift_emails (created_at DESC);

CREATE TABLE IF NOT EXISTS swift_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

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
);

CREATE INDEX IF NOT EXISTS swift_products_status_idx
    ON swift_products (status, name);
