-- Give items back the attempts they burned on URLs we never could have fetched.
--
-- Protocol-relative ("//cdn.example.com/x.jpg") and root-relative image srcs
-- were passed to httpx as-is, which rejects them outright ("Request URL is
-- missing an 'http://' or 'https://' protocol"). Those items were charged a
-- failed attempt per pass and some have already dropped out of the backfill
-- queue for good, even though the picture itself is perfectly fetchable once
-- the URL is resolved against the item's own URL.
--
-- Clearing the counter re-queues exactly those rows; items that failed for any
-- other reason keep their backoff.
UPDATE items
SET image_embed_attempts  = 0,
    image_embed_failed_at = NULL,
    image_embed_error     = NULL
WHERE image_embed_error ILIKE '%UnsupportedProtocol%';
