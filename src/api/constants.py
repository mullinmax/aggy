from config import config

# Server-wide default for how often sources are checked; individual sources
# can override it via sources.ingest_interval_minutes.
SOURCE_READ_INTERVAL_MINUTES = config.get_int("SOURCE_READ_INTERVAL_MINUTES")
