-- Renaming a feed changes its name_hash (the hash is derived from the name).
-- Every table keyed on a feed references feeds(user_hash, name_hash) with
-- ON DELETE CASCADE only; add ON UPDATE CASCADE so a rename carries the new
-- key through to sources, feed items, item states, and model stats instead of
-- being rejected by the foreign keys. (source_items already cascades updates
-- from sources, so a change to sources.feed_hash reaches it in turn.)
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT conrelid::regclass::text AS tbl, conname AS con
        FROM pg_constraint
        WHERE contype = 'f'
          AND confrelid = 'feeds'::regclass
          AND conrelid IN (
              'sources'::regclass,
              'feed_items'::regclass,
              'item_states'::regclass,
              'ranking_model_stats'::regclass
          )
    LOOP
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', r.tbl, r.con);
    END LOOP;
END $$;

ALTER TABLE sources
    ADD FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE feed_items
    ADD FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE item_states
    ADD FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash)
        ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE ranking_model_stats
    ADD FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash)
        ON DELETE CASCADE ON UPDATE CASCADE;
