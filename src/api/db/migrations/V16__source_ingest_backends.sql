-- Sources used to be, without exception, "a URL that returns RSS/Atom".
-- They now name the backend that turns them into items, so aggy can gather
-- articles from places that don't publish a feed at all:
--   'rss'   - fetch the URL and parse it as RSS/Atom (the existing behaviour)
--   'ytdlp' - enumerate a channel/user/playlist/search page of a video site
--   'html'  - render the page in a headless browser, then apply CSS selectors
-- `config` carries whatever settings that backend needs (CSS selectors, a
-- cookie header, an entry limit); NULL for plain RSS sources.
ALTER TABLE sources ADD COLUMN kind TEXT NOT NULL DEFAULT 'rss';
ALTER TABLE sources ADD COLUMN config JSONB;

-- Templates declare which backend the sources they create should use, so a
-- template can point at a video site or a scraped page rather than a feed.
ALTER TABLE source_templates ADD COLUMN kind TEXT NOT NULL DEFAULT 'rss';
