-- Give items back the attempts they burned on URLs we never could have fetched.
--
-- Two shapes of image URL were handed to httpx as-is and rejected before any
-- request went out ("UnsupportedProtocol"): protocol-relative and root-relative
-- srcs ("//cdn.example.com/x.jpg", "/img/x.jpg"), which are perfectly fetchable
-- once resolved against the item's own URL, and data: URIs, which carry the
-- picture itself and are now read directly instead of being downloaded.
--
-- Those items were charged a failed attempt per pass and some have already
-- dropped out of the backfill queue for good. Clearing the counter re-queues
-- exactly those rows; items that failed for any other reason keep their
-- backoff.
UPDATE items
SET image_embed_attempts  = 0,
    image_embed_failed_at = NULL,
    image_embed_error     = NULL
WHERE image_embed_error ILIKE '%UnsupportedProtocol%';
