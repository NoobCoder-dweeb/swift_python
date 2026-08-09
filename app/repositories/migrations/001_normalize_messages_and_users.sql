-- Upgrade the pre-normalisation schema without discarding application data.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'swift_thread_messages'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'swift_messages'
    ) THEN
        ALTER TABLE swift_thread_messages RENAME TO swift_messages;
    END IF;
END $$;

ALTER TABLE IF EXISTS swift_users ADD COLUMN IF NOT EXISTS user_id UUID DEFAULT gen_random_uuid();
UPDATE swift_users SET user_id = gen_random_uuid() WHERE user_id IS NULL;
ALTER TABLE IF EXISTS swift_users ALTER COLUMN user_id SET NOT NULL;

ALTER TABLE IF EXISTS swift_audits ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;
ALTER TABLE IF EXISTS swift_audits ADD COLUMN IF NOT EXISTS approver_user_id UUID;
ALTER TABLE IF EXISTS swift_messages ADD COLUMN IF NOT EXISTS audit_id TEXT;
ALTER TABLE IF EXISTS swift_messages ADD COLUMN IF NOT EXISTS approver_user_id UUID;
ALTER TABLE IF EXISTS swift_messages ADD COLUMN IF NOT EXISTS source_type TEXT;
ALTER TABLE IF EXISTS swift_messages ADD COLUMN IF NOT EXISTS source_id TEXT;
ALTER TABLE IF EXISTS swift_emails ADD COLUMN IF NOT EXISTS message_id TEXT;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'swift_audits' AND column_name = 'timestamp') THEN
        UPDATE swift_audits
        SET occurred_at = COALESCE(occurred_at, NULLIF(timestamp, '')::timestamptz);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'swift_audits' AND column_name = 'approver_username') THEN
        UPDATE swift_audits a
        SET approver_user_id = u.user_id
        FROM swift_users u
        WHERE a.approver_user_id IS NULL AND lower(a.approver_username) = lower(u.username);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'swift_messages' AND column_name = 'source_type') THEN
        UPDATE swift_messages
        SET audit_id = source_id
        WHERE audit_id IS NULL AND source_type = 'audit';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'swift_messages' AND column_name = 'approver_username') THEN
        UPDATE swift_messages m
        SET approver_user_id = u.user_id
        FROM swift_users u
        WHERE m.approver_user_id IS NULL AND lower(m.approver_username) = lower(u.username);
    END IF;
END $$;

-- Every legacy email already had a deterministic projected message ID. Missing
-- projections are repaired before email content columns are removed.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'swift_emails' AND column_name = 'sender') THEN
        INSERT INTO swift_threads (
            thread_id, sender, sender_key, subject, subject_key, created_at, updated_at
        )
        SELECT
            'THR-' || upper(substr(md5(lower(trim(e.sender)) || '|' || lower(regexp_replace(e.subject, '^(?:(?:re|fw|fwd)\s*:\s*)+', '', 'i'))), 1, 8)),
            e.sender,
            lower(trim(regexp_replace(e.sender, '^.*<([^>]+)>.*$', '\1'))),
            e.subject,
            lower(trim(regexp_replace(e.subject, '^(?:(?:re|fw|fwd)\s*:\s*)+', '', 'i'))),
            NULLIF(e.created_at, '')::timestamptz,
            COALESCE(NULLIF(e.updated_at, '')::timestamptz, NULLIF(e.created_at, '')::timestamptz)
        FROM swift_emails e
        ON CONFLICT (sender_key, subject_key) DO NOTHING;

        INSERT INTO swift_messages (
            message_id, thread_id, source_type, source_id, version_id, kind, sender, subject, body,
            timestamp, action, approver, emailed_to, sent, review_comment, payload
        )
        SELECT
            e.email_id || '-customer', t.thread_id, 'email', e.email_id, NULL, 'customer', e.sender,
            e.subject, e.body, e.created_at, NULL, NULL, NULL, FALSE, NULL,
            jsonb_build_object(
                'message_id', e.email_id || '-customer', 'thread_id', t.thread_id,
                'source_type', 'email', 'source_id', e.email_id, 'kind', 'customer',
                'sender', e.sender, 'subject', e.subject, 'body', e.body,
                'timestamp', e.created_at, 'sent', FALSE
            )
        FROM swift_emails e
        JOIN swift_threads t
          ON t.sender_key = lower(trim(regexp_replace(e.sender, '^.*<([^>]+)>.*$', '\1')))
         AND t.subject_key = lower(trim(regexp_replace(e.subject, '^(?:(?:re|fw|fwd)\s*:\s*)+', '', 'i')))
        ON CONFLICT (message_id) DO NOTHING;

        UPDATE swift_emails SET message_id = email_id || '-customer' WHERE message_id IS NULL;

        DELETE FROM swift_messages duplicate
        USING swift_emails e, swift_messages canonical
        WHERE e.message_id = canonical.message_id
          AND duplicate.source_type = 'audit'
          AND duplicate.kind = 'customer'
          AND duplicate.thread_id = canonical.thread_id
          AND duplicate.sender = canonical.sender
          AND lower(trim(regexp_replace(duplicate.subject, '^(?:(?:re|fw|fwd)\s*:\s*)+', '', 'i')))
              = lower(trim(regexp_replace(canonical.subject, '^(?:(?:re|fw|fwd)\s*:\s*)+', '', 'i')))
          AND trim(duplicate.body) = trim(canonical.body);
    END IF;
END $$;

-- Convert legacy textual event times before replacing the old columns.
ALTER TABLE IF EXISTS swift_messages ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'swift_messages' AND column_name = 'timestamp') THEN
        UPDATE swift_messages
        SET occurred_at = COALESCE(occurred_at, NULLIF(timestamp, '')::timestamptz, now());
    END IF;
END $$;
UPDATE swift_messages SET occurred_at = now() WHERE occurred_at IS NULL;
ALTER TABLE IF EXISTS swift_messages ALTER COLUMN occurred_at SET NOT NULL;

UPDATE swift_threads
SET created_at = COALESCE(NULLIF(created_at, ''), now()::text),
    updated_at = COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''), now()::text);
ALTER TABLE swift_threads
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz,
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at::timestamptz;
UPDATE swift_emails
SET created_at = COALESCE(NULLIF(created_at, ''), now()::text),
    updated_at = NULLIF(updated_at, '');
ALTER TABLE swift_emails
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz,
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at::timestamptz;
ALTER TABLE IF EXISTS swift_settings
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at::timestamptz;

-- Replace username identity with an immutable UUID identity.
ALTER TABLE IF EXISTS swift_audits DROP CONSTRAINT IF EXISTS swift_audits_approver_username_fkey;
ALTER TABLE IF EXISTS swift_messages DROP CONSTRAINT IF EXISTS swift_thread_messages_approver_username_fkey;
ALTER TABLE IF EXISTS swift_messages DROP CONSTRAINT IF EXISTS swift_messages_approver_username_fkey;
ALTER TABLE IF EXISTS swift_users DROP CONSTRAINT IF EXISTS swift_users_pkey;
ALTER TABLE IF EXISTS swift_users ADD CONSTRAINT swift_users_pkey PRIMARY KEY (user_id);
ALTER TABLE IF EXISTS swift_users DROP CONSTRAINT IF EXISTS swift_users_username_key;
ALTER TABLE IF EXISTS swift_users ADD CONSTRAINT swift_users_username_key UNIQUE (username);

ALTER TABLE IF EXISTS swift_audits DROP CONSTRAINT IF EXISTS swift_audits_approver_user_id_fkey;
ALTER TABLE IF EXISTS swift_audits
    ADD CONSTRAINT swift_audits_approver_user_id_fkey
    FOREIGN KEY (approver_user_id) REFERENCES swift_users(user_id);
ALTER TABLE IF EXISTS swift_messages DROP CONSTRAINT IF EXISTS swift_messages_approver_user_id_fkey;
ALTER TABLE IF EXISTS swift_messages
    ADD CONSTRAINT swift_messages_approver_user_id_fkey
    FOREIGN KEY (approver_user_id) REFERENCES swift_users(user_id);
UPDATE swift_messages m
SET audit_id = NULL
WHERE audit_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM swift_audits a WHERE a.audit_id = m.audit_id);
ALTER TABLE IF EXISTS swift_messages DROP CONSTRAINT IF EXISTS swift_messages_audit_id_fkey;
ALTER TABLE IF EXISTS swift_messages
    ADD CONSTRAINT swift_messages_audit_id_fkey
    FOREIGN KEY (audit_id) REFERENCES swift_audits(audit_id) ON DELETE SET NULL;
ALTER TABLE IF EXISTS swift_emails DROP CONSTRAINT IF EXISTS swift_emails_message_id_fkey;
ALTER TABLE IF EXISTS swift_emails
    ADD CONSTRAINT swift_emails_message_id_fkey
    FOREIGN KEY (message_id) REFERENCES swift_messages(message_id) ON DELETE CASCADE;
ALTER TABLE IF EXISTS swift_emails ALTER COLUMN message_id SET NOT NULL;
ALTER TABLE IF EXISTS swift_emails DROP CONSTRAINT IF EXISTS swift_emails_message_id_key;
ALTER TABLE IF EXISTS swift_emails ADD CONSTRAINT swift_emails_message_id_key UNIQUE (message_id);
ALTER TABLE IF EXISTS swift_messages DROP CONSTRAINT IF EXISTS swift_messages_audit_id_kind_key;
ALTER TABLE IF EXISTS swift_messages ADD CONSTRAINT swift_messages_audit_id_kind_key UNIQUE (audit_id, kind);

DROP INDEX IF EXISTS swift_thread_messages_thread_idx;
CREATE INDEX IF NOT EXISTS swift_messages_thread_idx ON swift_messages (thread_id, occurred_at);
DROP INDEX IF EXISTS swift_audits_action_idx;
CREATE INDEX IF NOT EXISTS swift_audits_action_idx ON swift_audits (action, occurred_at DESC);

ALTER TABLE IF EXISTS swift_audits DROP COLUMN IF EXISTS timestamp;
ALTER TABLE IF EXISTS swift_audits DROP COLUMN IF EXISTS approver_username;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS timestamp;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS source_type;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS source_id;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS approver_username;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS payload;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS draft_id;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS email_id;
ALTER TABLE IF EXISTS swift_emails DROP COLUMN IF EXISTS sender;
ALTER TABLE IF EXISTS swift_emails DROP COLUMN IF EXISTS subject;
ALTER TABLE IF EXISTS swift_emails DROP COLUMN IF EXISTS body;
ALTER TABLE IF EXISTS swift_emails DROP COLUMN IF EXISTS payload;
