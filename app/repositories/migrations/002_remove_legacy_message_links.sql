-- Databases upgraded with the initial normalisation migration may still have
-- nullable link columns from the oldest thread-message schema.
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS draft_id;
ALTER TABLE IF EXISTS swift_messages DROP COLUMN IF EXISTS email_id;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'swift_thread_messages_pkey') THEN
        ALTER TABLE swift_messages
            RENAME CONSTRAINT swift_thread_messages_pkey TO swift_messages_pkey;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'swift_thread_messages_thread_id_fkey'
    ) THEN
        ALTER TABLE swift_messages
            RENAME CONSTRAINT swift_thread_messages_thread_id_fkey
            TO swift_messages_thread_id_fkey;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'swift_thread_messages_kind_check') THEN
        ALTER TABLE swift_messages
            RENAME CONSTRAINT swift_thread_messages_kind_check
            TO swift_messages_kind_check;
    END IF;
END $$;
