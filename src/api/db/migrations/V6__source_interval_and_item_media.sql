-- Per-source ingest frequency override, in minutes.
-- NULL means "use the server-wide SOURCE_READ_INTERVAL_MINUTES default".
ALTER TABLE sources ADD COLUMN ingest_interval_minutes INTEGER;

-- Rich media (gifs, videos, image galleries) extracted at ingest time,
-- e.g. from reddit posts. A JSON array of {type, url, poster?} objects.
ALTER TABLE items ADD COLUMN media JSONB;
