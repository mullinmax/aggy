-- User "lists" (playlist-like collections of items).
--
-- Lists belong to a user and span feeds: any item the user can see may be
-- dropped into one or more lists. Membership in a list also feeds the ranking
-- model as an extra positive signal (see ranking/engine.py), so a listed item
-- is treated like an upvote even without an explicit vote.

CREATE TABLE lists (
    user_hash  TEXT NOT NULL REFERENCES users(name_hash) ON DELETE CASCADE,
    name_hash  TEXT NOT NULL,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_hash, name_hash)
);

CREATE TABLE list_items (
    user_hash     TEXT NOT NULL,
    list_hash     TEXT NOT NULL,
    item_url_hash TEXT NOT NULL REFERENCES items(url_hash) ON DELETE CASCADE,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_hash, list_hash, item_url_hash),
    FOREIGN KEY (user_hash, list_hash)
        REFERENCES lists(user_hash, name_hash) ON DELETE CASCADE
);

-- Ranking joins list membership per (user, item) across the feed's items.
CREATE INDEX list_items_user_item_idx ON list_items(user_hash, item_url_hash);
