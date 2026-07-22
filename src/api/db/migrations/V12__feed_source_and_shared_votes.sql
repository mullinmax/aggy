-- Feed-as-source and shared votes.
--
-- 1. A source may reference another of the user's feeds instead of an RSS URL.
--    When ``source_feed_hash`` is set the source is a "feed source": it is not
--    fetched over HTTP; instead the referenced feed's items are mirrored into
--    this source (and its parent feed) by the ingest fan-out. ``source_feed_hash``
--    is NULL for ordinary RSS sources.
--
-- 2. A vote is conceptually about the item, not the feed it happened to be cast
--    in. The ``user_item_votes`` view exposes the latest vote a user placed on
--    an item across all of their feeds, so every feed the item appears in can
--    train its ranking model on that vote.

ALTER TABLE sources
    ADD COLUMN source_feed_hash TEXT;

-- Renaming the referenced feed changes its name_hash (the hash is derived from
-- the name); cascade the update so the link survives. Deleting the referenced
-- feed removes the mirror source. Rows with a NULL source_feed_hash are exempt
-- from this foreign key: a composite FK with any NULL column is not enforced
-- (MATCH SIMPLE), so ordinary RSS sources are unaffected.
ALTER TABLE sources
    ADD FOREIGN KEY (user_hash, source_feed_hash)
        REFERENCES feeds(user_hash, name_hash)
        ON DELETE CASCADE ON UPDATE CASCADE;

-- Feed sources are never HTTP-ingested; keep them out of the ingest queue.
CREATE INDEX sources_source_feed_idx ON sources(user_hash, source_feed_hash)
    WHERE source_feed_hash IS NOT NULL;

-- Shared votes: the most recent non-null vote each user cast on each item,
-- regardless of which feed it was cast in. Ties on score_date resolve
-- arbitrarily (a user rarely votes on the same item twice in the same instant).
CREATE VIEW user_item_votes AS
SELECT DISTINCT ON (user_hash, item_url_hash)
    user_hash,
    item_url_hash,
    score,
    score_date
FROM item_states
WHERE score IS NOT NULL
ORDER BY user_hash, item_url_hash, score_date DESC NULLS LAST;
