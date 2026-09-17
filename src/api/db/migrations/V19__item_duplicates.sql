-- Near-duplicate article detection, canonical-URL signal.
--
-- The same article reaches a user through several sources, and reaches each of
-- them under a different URL: one carries the RSS reader's utm_source, one is
-- the AMP rendition, one came via a Google News redirect. items.url_hash is a
-- hash of the raw URL, so each of those is a separate item and the feed shows
-- the same piece three times.
--
-- ``canonical_url`` is the URL with everything that does not identify the
-- content removed (see dedup/canonical.py). Two items whose canonical URLs
-- match are the same article, which is as close to certain as this gets --
-- hence the exact-equality index on the hash rather than anything fuzzy.
--
-- Detection is item-level and user-independent: two items either are or are
-- not the same content. Which member of a group is *shown* is decided per user
-- per feed at query time, because the prediction it is decided by lives on
-- feed_items.
--
-- Note there is no V15; the tree goes V14, V16, V17, V18. The gap is
-- deliberate -- Flyway does not mind, and filling it would break installs that
-- have already migrated past it.

ALTER TABLE items
    ADD COLUMN canonical_url      TEXT,
    ADD COLUMN canonical_url_hash TEXT,
    ADD COLUMN dedup_computed_at  TIMESTAMPTZ;

CREATE INDEX items_canonical_url_hash_idx ON items(canonical_url_hash)
    WHERE canonical_url_hash IS NOT NULL;

-- The detection job's work queue. Existing installs start with every row
-- pending, which is fine: a NULL dedup_computed_at simply means "not in a
-- group yet", and the feed keeps working throughout the backfill.
CREATE INDEX items_dedup_pending_idx ON items(created_at)
    WHERE dedup_computed_at IS NULL;

-- Star topology: every member points at its group, and the representative is
-- the row whose item_url_hash equals its group_hash. A new item joins only if
-- it matches the representative -- never merely some member -- because the
-- transitive closure of "near enough" is how a 400-item mega-group happens.
--
-- The representative is only the grouping anchor. The member actually shown is
-- whichever the current model scores highest, which changes as the model does.
CREATE TABLE item_duplicates (
    item_url_hash TEXT PRIMARY KEY REFERENCES items(url_hash) ON DELETE CASCADE,
    group_hash    TEXT NOT NULL,
    signal        TEXT NOT NULL,  -- canonical_url (more to come)
    confidence    DOUBLE PRECISION NOT NULL,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX item_duplicates_group_idx ON item_duplicates(group_hash);
