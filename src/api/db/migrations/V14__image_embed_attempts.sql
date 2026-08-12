-- Track image-embedding attempts per item.
--
-- The backfill previously picked the newest items missing an embedding and left
-- no trace when one failed, so a batch of permanently unfetchable pictures
-- (expired reddit signed URLs, 404s, hosts serving HTML instead of an image)
-- was re-selected and re-failed on every single pass. The queue never advanced
-- past them and the older backlog was never reached.
--
-- Recording the attempt lets the backfill back off failing items exponentially
-- and always spend its budget on items that have a chance of succeeding.
ALTER TABLE items
    ADD COLUMN image_embed_attempts  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN image_embed_failed_at TIMESTAMPTZ,
    ADD COLUMN image_embed_error     TEXT;

-- The backfill orders by (attempts, created_at DESC): never-tried items first,
-- newest first within a tier. Kept unpartitioned so the planner can walk it in
-- order for that sort -- the remaining conditions (which model's vector is
-- missing) are parameters, which a partial index can't be built on.
CREATE INDEX items_image_embed_backfill_idx
    ON items (image_embed_attempts, created_at DESC);
