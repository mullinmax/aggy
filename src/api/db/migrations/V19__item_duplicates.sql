-- Near-duplicate article detection, canonical-URL signal, scoped per account.
--
-- The same article reaches a user through several sources, and reaches each of
-- them under a different URL: one carries the RSS reader's utm_source, one is
-- the AMP rendition, one came via a Google News redirect. items.url_hash is a
-- hash of the raw URL, so each of those is a separate item and the feed shows
-- the same piece three times.
--
-- ``canonical_url`` is the URL with everything that does not identify the
-- content removed (see dedup/canonical.py). It lives on ``items`` because it is
-- derived from that item's own URL and nothing else -- no content, no account.
--
-- Matching, though, is per account. Two users holding the same article are
-- never compared against each other, and a group only ever contains items one
-- account holds. That is a deliberate boundary rather than a consequence:
--
--   * A shared group would let one account's data change another's feed. With
--     one global group, DUPLICATE_MAX_GROUP counts strangers' copies, so a
--     widely-held article fills the group and your own two copies stop being
--     grouped together.
--   * The text and image signals still to come compare article *content*. Doing
--     that across accounts would compare what you collected against what
--     somebody else collected, which is exactly the comparison this boundary
--     exists to prevent.
--
-- Note there is no V15; the tree goes V14, V16, V17, V18. The gap is
-- deliberate -- Flyway does not mind, and filling it would break installs that
-- have already migrated past it.

ALTER TABLE items
    ADD COLUMN canonical_url      TEXT,
    ADD COLUMN canonical_url_hash TEXT;

CREATE INDEX items_canonical_url_hash_idx ON items(canonical_url_hash)
    WHERE canonical_url_hash IS NOT NULL;

-- One row per (account, item) the detector has examined.
--
-- A NULL group_hash means "examined, and not a duplicate of anything this
-- account holds". Those rows are the work queue for the re-sweep: an item can
-- become a duplicate later, when a second copy arrives or a threshold changes,
-- and without them there would be no record of having looked.
--
-- Star topology: every member points at its group, and the representative is
-- the row whose item_url_hash equals its group_hash. A new item joins only if
-- it matches the representative -- never merely some member -- because the
-- transitive closure of "near enough" is how a 400-item mega-group happens.
--
-- The representative is only the grouping anchor. The member actually shown is
-- whichever the current model scores highest, which changes as the model does.
CREATE TABLE item_duplicates (
    user_hash     TEXT NOT NULL REFERENCES users(name_hash) ON DELETE CASCADE,
    item_url_hash TEXT NOT NULL REFERENCES items(url_hash) ON DELETE CASCADE,
    group_hash    TEXT,
    signal        TEXT,  -- canonical_url (more to come); NULL when ungrouped
    confidence    DOUBLE PRECISION,
    checked_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (user_hash, item_url_hash)
);

-- Reading a group: always within one account.
CREATE INDEX item_duplicates_group_idx ON item_duplicates(user_hash, group_hash)
    WHERE group_hash IS NOT NULL;

-- The re-sweep queue: items examined and found unique, oldest check first.
CREATE INDEX item_duplicates_recheck_idx ON item_duplicates(checked_at)
    WHERE group_hash IS NULL;
