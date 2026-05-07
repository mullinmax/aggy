-- Initial schema for Aggy
-- Replaces the previous Redis/Valkey based key-value model.

CREATE TABLE users (
    name_hash       TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE feeds (
    user_hash  TEXT NOT NULL REFERENCES users(name_hash) ON DELETE CASCADE,
    name_hash  TEXT NOT NULL,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_hash, name_hash)
);

CREATE TABLE sources (
    user_hash      TEXT NOT NULL,
    feed_hash      TEXT NOT NULL,
    name_hash      TEXT NOT NULL,
    name           TEXT NOT NULL,
    url            TEXT NOT NULL,
    next_ingest_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_hash, feed_hash, name_hash),
    FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash) ON DELETE CASCADE
);

CREATE INDEX sources_next_ingest_idx ON sources(next_ingest_at);

CREATE TABLE items (
    url_hash       TEXT PRIMARY KEY,
    url            TEXT NOT NULL,
    title          TEXT,
    author         TEXT,
    domain         TEXT,
    excerpt        TEXT,
    content        TEXT,
    image_url      TEXT,
    date_published TIMESTAMPTZ,
    embeddings     JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Replaces the per-feed Redis ZSET of (item_url_hash -> score)
CREATE TABLE feed_items (
    user_hash     TEXT NOT NULL,
    feed_hash     TEXT NOT NULL,
    item_url_hash TEXT NOT NULL REFERENCES items(url_hash) ON DELETE CASCADE,
    score         DOUBLE PRECISION NOT NULL DEFAULT 0,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_hash, feed_hash, item_url_hash),
    FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash) ON DELETE CASCADE
);

-- Replaces the per-source Redis ZSET of (item_url_hash -> score)
CREATE TABLE source_items (
    user_hash     TEXT NOT NULL,
    feed_hash     TEXT NOT NULL,
    source_hash   TEXT NOT NULL,
    item_url_hash TEXT NOT NULL REFERENCES items(url_hash) ON DELETE CASCADE,
    score         DOUBLE PRECISION NOT NULL DEFAULT 0,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_hash, feed_hash, source_hash, item_url_hash),
    FOREIGN KEY (user_hash, feed_hash, source_hash)
        REFERENCES sources(user_hash, feed_hash, name_hash) ON DELETE CASCADE
);

CREATE TABLE item_states (
    user_hash     TEXT NOT NULL REFERENCES users(name_hash) ON DELETE CASCADE,
    feed_hash     TEXT NOT NULL,
    item_url_hash TEXT NOT NULL,
    score         DOUBLE PRECISION,
    score_date    TIMESTAMPTZ,
    is_read       BOOLEAN,
    PRIMARY KEY (user_hash, feed_hash, item_url_hash),
    FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash) ON DELETE CASCADE
);

CREATE TABLE source_templates (
    name_hash         TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    bridge_short_name TEXT,
    url               TEXT NOT NULL,
    description       TEXT NOT NULL,
    context           TEXT,
    parameters        JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
