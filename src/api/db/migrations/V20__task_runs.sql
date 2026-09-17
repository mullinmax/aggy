-- What the background jobs are doing, and how long each pass took.
--
-- Aggy does most of its work on a scheduler: sources are ingested, models are
-- retrained, articles are scored, duplicates are grouped, preview images are
-- embedded. Until now none of that was visible. ranking.progress tracks a
-- training run while it is in flight and forgets it on the next deploy;
-- source_ingest_attempts records that an ingest happened but not how long it
-- took; everything else left only a log line.
--
-- One row per pass, with both ends of it, so the tasks page can draw a bar per
-- run and answer the two questions a log cannot: how often does this run, and
-- how long does it take.
--
-- user_hash is NULL for a system-wide pass. Duplicate detection and the image
-- backfill work a global queue rather than one account's, and claiming
-- otherwise on a per-account page would be a lie -- so they are stored
-- unowned and labelled as system-wide when shown.
--
-- Rows are pruned to TASK_RUN_HISTORY_DAYS by the same job that trims the
-- ingest attempt history.
CREATE TABLE task_runs (
    id          BIGSERIAL PRIMARY KEY,
    user_hash   TEXT REFERENCES users(name_hash) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    -- what the pass was working on: a feed name, a source name. NULL for a
    -- system-wide pass, which works no single thing.
    target      TEXT,
    status      TEXT NOT NULL,
    -- one line for the table and the tooltip: counts on success, the reason on
    -- failure
    detail      TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- NULL while the pass is still running
    finished_at TIMESTAMPTZ,

    CONSTRAINT task_runs_status_check
        CHECK (status IN ('running', 'ok', 'error'))
);

-- The page's own query is "this account's recent runs, plus the system-wide
-- ones", which is two reads rather than one: an index on (user_hash, ...)
-- cannot serve the NULL side usefully, since every account wants those same
-- rows. Hence one index per side.
CREATE INDEX task_runs_user_time_idx ON task_runs (user_hash, started_at DESC);
CREATE INDEX task_runs_system_time_idx ON task_runs (started_at DESC)
    WHERE user_hash IS NULL;

-- Pruning deletes by age across all accounts.
CREATE INDEX task_runs_started_at_idx ON task_runs (started_at);

-- Runs still marked running: the live rows the page shows, and the ones a
-- restart has to clean up after a process died mid-pass.
CREATE INDEX task_runs_running_idx ON task_runs (id) WHERE status = 'running';
