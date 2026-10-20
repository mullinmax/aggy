-- A navigable small-world graph of similar articles, per account per feed.
--
-- Duplicate detection so far had exactly one signal: two items whose URLs
-- reduce to the same canonical string are the same article. That catches the
-- same link arriving from three sources and nothing else. The story rewritten
-- by a second outlet, the press release and the article about it, the same
-- video posted to two channels -- all of them read as distinct articles under
-- distinct URLs, because they are distinct URLs.
--
-- What actually distinguishes them is content, and every item already carries
-- a text embedding of its content. The obstacle is cost: comparing a new
-- article against every other one this account holds is a full scan of the
-- feed and a dot product per row, on every ingest, forever. Postgres here has
-- no vector index (embeddings are JSONB, keyed by model name), so there is
-- nothing to push the search down into.
--
-- Hence a graph. Each article stores a short list of its nearest neighbours,
-- and a new article is placed by *walking* that graph rather than scanning it:
-- start from a few entry points, hop to whichever neighbour is closer to the
-- new article, and stop at a local minimum. That visits a few dozen articles
-- instead of tens of thousands, and the walk falls out of the same structure
-- that answers "what else is like this one?" for the reader.
--
-- The links are a genuine approximation. A greedy walk over an approximate
-- graph finds a local minimum, not a guaranteed global one, which is why
-- collapsing two articles as duplicates needs a similarity high enough that a
-- near-miss on the true nearest neighbour does not matter -- and why an
-- article that *would* have matched is simply left uncollapsed rather than
-- wrongly merged. That is the same bias the canonical-URL signal already has.
--
-- Scope is (account, feed), matching feed_items:
--
--   * Per account for the same reason item_duplicates is (see V21): this
--     compares article *content*, and that comparison must not cross accounts.
--   * Per feed because the reader's "related articles" rail is a feed-local
--     question -- the answer has to come from the feed you are reading -- and
--     because a feed is a topical cluster, so the walk converges faster inside
--     one than across all of an account's articles at once.
--
-- The cost is that an item in several feeds is linked once per feed. That is
-- the same shape feed_items itself has, and each feed's answer is genuinely
-- different, so it is duplicated work rather than wasted work.

-- One directed edge: `item_url_hash` names `neighbor_url_hash` as one of its
-- nearest. Edges are written in both directions when an article is linked, but
-- they are trimmed per node, so the graph does not stay symmetric -- a popular
-- node is named by far more articles than it names back. Both directions are
-- read when walking, which is what keeps a node reachable after its own list
-- has moved on.
CREATE TABLE item_neighbors (
    user_hash         TEXT NOT NULL,
    feed_hash         TEXT NOT NULL,
    item_url_hash     TEXT NOT NULL,
    neighbor_url_hash TEXT NOT NULL,
    -- Cosine similarity of the two text embeddings, in [-1, 1]. Stored rather
    -- than recomputed: the walk compares candidates against each other
    -- constantly, and re-reading two JSONB vectors to do it is the whole cost.
    similarity        DOUBLE PRECISION NOT NULL,
    linked_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (user_hash, feed_hash, item_url_hash, neighbor_url_hash),
    -- An article that leaves a feed takes its edges with it, in both
    -- directions -- a dangling edge would send the walk to a node the feed no
    -- longer holds.
    FOREIGN KEY (user_hash, feed_hash, item_url_hash)
        REFERENCES feed_items(user_hash, feed_hash, item_url_hash)
        ON DELETE CASCADE,
    FOREIGN KEY (user_hash, feed_hash, neighbor_url_hash)
        REFERENCES feed_items(user_hash, feed_hash, item_url_hash)
        ON DELETE CASCADE,
    CHECK (item_url_hash <> neighbor_url_hash)
);

-- Reading the back-edges into a node, and cascading a removal. The forward
-- direction is already the primary key's prefix.
CREATE INDEX item_neighbors_reverse_idx
    ON item_neighbors(user_hash, feed_hash, neighbor_url_hash);

-- Per-node graph state, on feed_items because that is exactly the grain: one
-- row per (account, feed, article), removed with the article's membership.
--
--   * neighbors_stale is the work queue. It defaults TRUE, so every row that
--     exists now and every row ingest writes from here on is queued -- which
--     is what backfills the graph over the next few passes. It is set again
--     when a newly linked article displaces one of a neighbour's links, since
--     that neighbour's own list may now be out of date.
--   * neighbors_linked_at is when the node was last walked. It orders the
--     queue (never-linked first, then oldest) and rate-limits re-walks, so a
--     node dirtied by every new arrival is not re-walked on every pass.
--   * neighbors_model records which embedding model the similarities were
--     computed from, for diagnosis. Cosine distances from two different models
--     are not comparable, so an operator who changes OLLAMA_EMBEDDING_MODEL
--     should rebuild the graph:
--         UPDATE feed_items SET neighbors_stale = TRUE, neighbors_linked_at = NULL;
--     It is not folded into the queue predicate because that would make every
--     pass scan the table forever to catch a change that happens approximately
--     never.
ALTER TABLE feed_items
    ADD COLUMN neighbors_linked_at TIMESTAMPTZ,
    ADD COLUMN neighbors_stale     BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN neighbors_model     TEXT;

-- The queue: stale nodes, never-linked ones first. Partial, because a settled
-- graph has almost nothing in it.
CREATE INDEX feed_items_neighbors_pending_idx
    ON feed_items(neighbors_linked_at NULLS FIRST)
    WHERE neighbors_stale;

-- The embedding signal joins canonical_url in item_duplicates.signal, which is
-- already a free-text column, so nothing changes there. What does change is
-- what `confidence` means for such a row: for canonical_url it is a flat 1.0,
-- and for text_embedding it is the measured cosine similarity of the two
-- articles, so a borderline collapse is visible as a borderline number.
