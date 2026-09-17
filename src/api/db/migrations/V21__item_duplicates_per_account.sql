-- Scope duplicate detection to one account.
--
-- V19 grouped items globally: two items either were or were not the same
-- content, regardless of who held them. That is wrong, for two reasons that
-- only became clear once the later signals were designed.
--
--   * A shared group lets one account's data change another's feed. With one
--     global group, DUPLICATE_MAX_GROUP counts strangers' copies, so a widely
--     held article fills the group and your own two copies stop being grouped
--     together. What your feed collapses should not depend on what anyone else
--     collected.
--   * The text and image signals still to come compare article *content*.
--     Across accounts that compares what you collected against what somebody
--     else collected, which is exactly the comparison this boundary exists to
--     prevent.
--
-- ``items.canonical_url`` and its hash stay exactly as V19 left them, already
-- backfilled. They are derived from an item's own URL and nothing else, so
-- they carry no account and need no scoping. Only the *matching* moves.
--
-- Note there is no V15; the tree goes V14, V16-V21. The gap is deliberate:
-- Flyway does not mind, and filling it would break installs that have already
-- migrated past it.

-- Examination is now recorded per (account, item) in item_duplicates below,
-- which is what the detector reads and what the re-sweep queue is built from.
-- A single column on items cannot say "examined for this account", so it goes.
DROP INDEX IF EXISTS items_dedup_pending_idx;
ALTER TABLE items DROP COLUMN IF EXISTS dedup_computed_at;

-- The old rows are dropped rather than translated, deliberately.
--
-- Every value in this table is derived: the detector recomputes it from
-- canonical_url, which V19 already backfilled and this migration leaves
-- untouched. Translating instead would mean splitting each global group into
-- the members each account happens to hold, and re-picking a representative
-- per account, without the publish-date window that the detector applies when
-- it builds a group. That could seed a group the detector itself would never
-- have made -- and since an item already in a group is never re-examined, a
-- wrongly seeded group would be permanent. An empty table simply refills,
-- correctly, so that is the safer of the two.
--
-- The cost is that an existing install re-examines its articles over the next
-- few detection passes, at DUPLICATE_DETECTION_BATCH_SIZE items each. The feed
-- keeps working throughout: an item with no row yet reads as "not in a group",
-- which is what every item looked like before V19 anyway.
DROP TABLE IF EXISTS item_duplicates;

-- One row per (account, item) the detector has examined.
--
-- A NULL group_hash means "examined, and not a duplicate of anything this
-- account holds". Those rows are the work queue for the re-sweep: an item can
-- become a duplicate later, when a second copy of the story arrives, and
-- without them there would be no record of having looked. V19 had no way to
-- express this -- group_hash was NOT NULL -- so an item found unique was
-- indistinguishable from one never examined.
--
-- Star topology: every member points at its group, and the representative is
-- the row whose item_url_hash equals its group_hash. A new item joins only if
-- it matches the representative -- never merely some member -- because the
-- transitive closure of "near enough" is how a 400-item mega-group happens.
--
-- The representative is only the grouping anchor, the member published first.
-- The member the feed actually shows is whichever the current model scores
-- highest, which changes as the model does.
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
