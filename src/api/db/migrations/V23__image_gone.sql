-- Remember when an image host said the picture is gone, not just that a fetch
-- failed.
--
-- The backfill treats every failure the same: back off, try again, and give up
-- after IMAGE_EMBED_MAX_ATTEMPTS. For a host answering 410 Gone -- which means
-- exactly "this is not coming back" -- that is five more requests over a week
-- to be told the same thing, while the items behind it wait.
--
-- It is also a fact the recommender should know. An article whose picture has
-- been removed is not the same article it was when it was posted, and how much
-- that matters depends on how central the picture was; the models can only
-- learn that if the difference reaches them, so this column is read as a
-- ranking feature alongside "has an image" rather than quietly clearing it.
ALTER TABLE items
    ADD COLUMN image_gone_at TIMESTAMPTZ;

-- The backfill's candidate scan filters on this, and retired items are a
-- growing share of the table over time: worth keeping them out of the scan
-- rather than reading and discarding them every pass.
CREATE INDEX items_image_gone_idx
    ON items (image_embed_attempts, created_at DESC)
    WHERE image_gone_at IS NULL;
