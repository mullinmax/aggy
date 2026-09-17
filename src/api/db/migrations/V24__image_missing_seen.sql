-- Remember the first time a picture came back 404, separately from the attempt
-- counter.
--
-- A 404 is retired on the second one, because a single 404 is also what a CDN
-- says mid-deploy. That second strike was counted with image_embed_attempts --
-- which the manual "retry failed images" button resets to zero. Anyone using
-- that button (its whole purpose is items stuck behind a backoff) therefore
-- re-armed every 404 in the table at "attempt one", and they were fetched
-- again, and again, forever: the count never reached two.
--
-- Recorded here instead, where a retry does not reach it. A re-scrape that
-- turns up a different picture still clears it, because that is a genuinely
-- new question rather than the same one asked twice.
ALTER TABLE items
    ADD COLUMN image_missing_at TIMESTAMPTZ;

-- Items already carrying a 404 have served their first strike; the next one
-- retires them rather than starting the count over. Only when *every* URL
-- tried answered 404, matching the rule the code applies: a 404 beside a 403
-- says nothing final, so strike out the 404s and require nothing else to be
-- left.
UPDATE items
SET image_missing_at = COALESCE(image_embed_failed_at, NOW())
WHERE image_gone_at IS NULL
  AND image_embed_error LIKE '%HTTP 404%'
  AND regexp_replace(image_embed_error, 'HTTP 404', '', 'g') NOT LIKE '%HTTP %';
