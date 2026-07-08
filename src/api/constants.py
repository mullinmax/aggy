from config import config

# Server-wide default for how often sources are checked; individual sources
# can override it via sources.ingest_interval_minutes.
SOURCE_READ_INTERVAL_MINUTES = config.get_int("SOURCE_READ_INTERVAL_MINUTES")

# Reddit sources get a slower default cadence: reddit rate-limits anonymous
# requests hard, and subreddit sources are locked to "top today", which a
# roughly twice-daily check covers almost completely.
REDDIT_SOURCE_READ_INTERVAL_MINUTES = config.get_int(
    "REDDIT_SOURCE_READ_INTERVAL_MINUTES"
)
