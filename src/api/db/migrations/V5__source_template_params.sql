-- Remember which template (and which parameter values) a source was created
-- from, so the UI can offer editing a source's parameters after creation.
ALTER TABLE sources
    ADD COLUMN template_name_hash TEXT,
    ADD COLUMN template_parameters JSONB;

-- Renaming a source changes its name_hash (the hash is derived from the
-- name), so the source_items FK must follow the new key.
DO $$
DECLARE con TEXT;
BEGIN
    SELECT conname INTO con
    FROM pg_constraint
    WHERE conrelid = 'source_items'::regclass
      AND contype = 'f'
      AND confrelid = 'sources'::regclass;
    EXECUTE format('ALTER TABLE source_items DROP CONSTRAINT %I', con);
END $$;

ALTER TABLE source_items
    ADD FOREIGN KEY (user_hash, feed_hash, source_hash)
        REFERENCES sources(user_hash, feed_hash, name_hash)
        ON DELETE CASCADE ON UPDATE CASCADE;
