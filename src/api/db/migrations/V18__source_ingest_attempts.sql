-- One row per ingest attempt, so the stats page can show how a site's
-- reliability moves over time rather than only its latest verdict.
--
-- sources.last_ingest_error keeps just the most recent failure, which cannot
-- answer "is YouTube getting worse?" or "was that outage an hour or a week?".
-- This table can, at the cost of a row per attempt -- pruned by the ingest
-- scheduler to SOURCE_ATTEMPT_HISTORY_DAYS.
--
-- The host is denormalized onto the row on purpose: it is what the page groups
-- by, and a source that has since been deleted or re-pointed should not take
-- its outage history with it.
CREATE TABLE source_ingest_attempts (
    id            BIGSERIAL PRIMARY KEY,
    user_hash     TEXT NOT NULL,
    feed_hash     TEXT NOT NULL,
    source_hash   TEXT NOT NULL,
    -- registrable domain of the source URL, e.g. "youtube.com"
    host          TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    -- the failure message, for the "most recent error" column; NULL on success
    error         TEXT,
    attempted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT source_ingest_attempts_outcome_check
        CHECK (outcome IN ('ok', 'error', 'skipped'))
);

-- The page's own query: one user's recent attempts, grouped by host.
CREATE INDEX source_ingest_attempts_user_time_idx
    ON source_ingest_attempts (user_hash, attempted_at DESC);

-- Pruning deletes by age across all users.
CREATE INDEX source_ingest_attempts_attempted_at_idx
    ON source_ingest_attempts (attempted_at);
