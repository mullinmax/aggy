-- Your own verdicts on whether two articles are the same story.
--
-- Detection collapses a pair when their embeddings are closer than
-- DUPLICATE_SIMILARITY_THRESHOLD, a constant picked by hand and deliberately
-- set high: the walk that finds candidates is approximate, and an uncollapsed
-- duplicate is a far cheaper mistake than an article you never get to see.
-- "High enough to be safe" is not the same as "right", and nothing in the
-- system could tell the difference, because nothing recorded what the right
-- answer was.
--
-- This is that record. A row is one pair you looked at and judged, and it is
-- used twice: as an instruction detection must obey (a pair you rejected is
-- never grouped again, a pair you confirmed is grouped whatever the cosine
-- says), and as a training label for a model that learns where the line
-- actually falls for your articles.
--
-- Per account, for the reason V21 gives at length: this is about article
-- content, and that comparison must not cross accounts. It is also simply a
-- personal judgement -- two people can reasonably disagree about whether a
-- rewrite is the same story.
CREATE TABLE duplicate_labels (
    user_hash    TEXT NOT NULL REFERENCES users(name_hash) ON DELETE CASCADE,
    -- The pair, ordered. Which article was on the left of the screen carries
    -- no meaning, so the hashes are stored sorted and the CHECK makes that
    -- the only representable form: one row per unordered pair, and a second
    -- verdict on the same pair updates the first rather than contradicting it
    -- from the other side.
    left_hash    TEXT NOT NULL REFERENCES items(url_hash) ON DELETE CASCADE,
    right_hash   TEXT NOT NULL REFERENCES items(url_hash) ON DELETE CASCADE,
    is_duplicate BOOLEAN NOT NULL,
    labeled_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (user_hash, left_hash, right_hash),
    CHECK (left_hash < right_hash)
);

-- Training reads every label an account has, newest first when it needs to
-- cap the set; the review queue asks "have I already judged this pair?" by
-- primary key, which the key above already serves.
CREATE INDEX duplicate_labels_user_idx ON duplicate_labels(user_hash, labeled_at DESC);

-- Rejecting a pair puts the member back in the feed, which means an article
-- can leave a group. Nothing else in the schema changes: item_duplicates
-- already expresses "examined, and not a duplicate of anything" as a NULL
-- group_hash, which is exactly what a split member becomes.
