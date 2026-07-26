from config import config

# Templates imported from RSSHub's route catalog carry this prefix in their
# bridge_short_name, which is what tells them apart from rss-bridge's (and
# what lets them be cleaned up when RSSHub goes away).
RSSHUB_TEMPLATE_PREFIX = "rsshub:"

# Where a template's feed comes from, shown as a label in the catalog.
PROVIDER_BUILTIN = "Built-in"
PROVIDER_RSS_BRIDGE = "RSS-Bridge"
PROVIDER_RSSHUB = "RSSHub"

# Browse order when nothing is being searched, and the tiebreak between
# equally-good matches when something is. Aggy's own templates are the most
# reliable (they fetch the site directly), and RSSHub's catalog is far the
# largest, so without this its thousands of routes bury everything else.
PROVIDER_RANK = {
    PROVIDER_BUILTIN: 0,
    PROVIDER_RSS_BRIDGE: 1,
    PROVIDER_RSSHUB: 2,
}

# Server-wide default for how often sources are checked; individual sources
# can override it via sources.ingest_interval_minutes.
SOURCE_READ_INTERVAL_MINUTES = config.get_int("SOURCE_READ_INTERVAL_MINUTES")

# Reddit sources get a slower default cadence: reddit rate-limits anonymous
# requests hard, and subreddit sources are locked to "top today", which a
# roughly twice-daily check covers almost completely.
REDDIT_SOURCE_READ_INTERVAL_MINUTES = config.get_int(
    "REDDIT_SOURCE_READ_INTERVAL_MINUTES"
)
