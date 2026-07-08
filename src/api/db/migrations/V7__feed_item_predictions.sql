-- Vote prediction: cached per-feed-item model predictions and per-feed
-- model evaluation stats.

ALTER TABLE feed_items
    ADD COLUMN predicted_score      DOUBLE PRECISION,
    ADD COLUMN predicted_confidence DOUBLE PRECISION,
    ADD COLUMN predicted_model      TEXT,
    ADD COLUMN predicted_at         TIMESTAMPTZ;

CREATE TABLE ranking_model_stats (
    user_hash     TEXT NOT NULL,
    feed_hash     TEXT NOT NULL,
    model_name    TEXT NOT NULL,
    n_labels      INTEGER NOT NULL,
    mae           DOUBLE PRECISION,
    rmse          DOUBLE PRECISION,
    sign_accuracy DOUBLE PRECISION,
    chosen        BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_hash, feed_hash, model_name),
    FOREIGN KEY (user_hash, feed_hash)
        REFERENCES feeds(user_hash, name_hash) ON DELETE CASCADE
);
