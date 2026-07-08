-- Reddit subreddit sources are now locked to "top today": reddit rate-limits
-- anonymous requests hard, and the day's top posts capture nearly everything
-- worth surfacing. Rewrite any existing subreddit RSS URL -- whatever sort it
-- used (hot/new/top/rising/controversial, or none) -- to the top-of-day feed,
-- and drop the now-unsupported "sort" template parameter.
UPDATE sources
SET url = regexp_replace(
        url,
        '^(https?://(?:www\.|old\.|new\.|np\.)?reddit\.com/r/[^/?#]+)(?:/(?:hot|new|top|rising|controversial))?/?\.rss.*$',
        '\1/top.rss?t=day'
    ),
    next_ingest_at = NOW()
WHERE url ~* '^https?://(?:www\.|old\.|new\.|np\.)?reddit\.com/r/[^/?#]+(?:/(?:hot|new|top|rising|controversial))?/?\.rss';

UPDATE sources
SET template_parameters = template_parameters - 'sort'
WHERE template_parameters ? 'sort'
  AND url ~* '^https?://(?:www\.|old\.|new\.|np\.)?reddit\.com/';

-- Give existing reddit sources (subreddit and user feeds) the slower reddit
-- cadence unless the user already set an explicit per-source interval. 720
-- minutes (~twice a day) is REDDIT_SOURCE_READ_INTERVAL_MINUTES's default.
UPDATE sources
SET ingest_interval_minutes = 720
WHERE ingest_interval_minutes IS NULL
  AND url ~* '^https?://(?:www\.|old\.|new\.|np\.)?reddit\.com/';
