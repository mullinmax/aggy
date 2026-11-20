-- Two things the recommender has never had: a record of what you opened, and
-- a place to keep the result of an experiment on it.
--
-- item_opens
--
-- A vote is the only thing the models learn from, and most articles you look
-- at never get one. item_states.is_read says an article was opened at some
-- point, but not when, not how often and not for how long -- so it cannot be
-- replayed in time, and "opened for two seconds and closed" is indistinguishable
-- from "read to the end".
--
-- One row per open. `surface` says how it was opened: in the reader, or by
-- following the link out to the original page. Only the reader can time
-- itself, so `seconds` stays NULL for a link-out and for a reader the browser
-- closed before it could report back. `seconds` counts time the reader was
-- actually on screen: a tab left open in the background does not accrue.
--
-- Nothing ranks on this yet. It is collected so the prediction experiments can
-- find out which of these signals actually goes with an upvote, which needs
-- the history to exist first.
CREATE TABLE item_opens (
    id            BIGSERIAL PRIMARY KEY,
    user_hash     TEXT NOT NULL REFERENCES users(name_hash) ON DELETE CASCADE,
    feed_hash     TEXT NOT NULL,
    item_url_hash TEXT NOT NULL REFERENCES items(url_hash) ON DELETE CASCADE,
    surface       TEXT NOT NULL,
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    seconds       DOUBLE PRECISION,

    FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash) ON DELETE CASCADE,
    CONSTRAINT item_opens_surface_check CHECK (surface IN ('reader', 'link')),
    CONSTRAINT item_opens_seconds_check CHECK (seconds IS NULL OR seconds >= 0)
);

CREATE INDEX item_opens_feed_idx ON item_opens (user_hash, feed_hash, opened_at);
CREATE INDEX item_opens_item_idx ON item_opens (user_hash, item_url_hash);

-- ranking_experiments
--
-- A prediction experiment replays a feed's vote history against every
-- candidate method, which can take many minutes. It is queued here and worked
-- one at a time by a background job, so asking for one returns at once, a page
-- refresh or a restart loses nothing, and old results stay readable.
--
-- `result` holds aggregate scores only (see ranking/experiments): no titles,
-- URLs, source names or embeddings, so it is safe to copy out of the app.
--
-- feed_hash is NULL for a run over every feed the account has. It is not a
-- foreign key: a result is still worth reading after its feed was deleted.
CREATE TABLE ranking_experiments (
    id          BIGSERIAL PRIMARY KEY,
    user_hash   TEXT NOT NULL REFERENCES users(name_hash) ON DELETE CASCADE,
    feed_hash   TEXT,
    -- what was asked for: mode, optional extras
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'queued',
    -- where a running experiment has got to, for the progress bar
    progress    JSONB,
    result      JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    CONSTRAINT ranking_experiments_status_check
        CHECK (status IN ('queued', 'running', 'done', 'error', 'cancelled'))
);

CREATE INDEX ranking_experiments_user_idx
    ON ranking_experiments (user_hash, created_at DESC);
-- The worker's own query: the oldest experiment still waiting or in flight.
CREATE INDEX ranking_experiments_open_idx
    ON ranking_experiments (id) WHERE status IN ('queued', 'running');
