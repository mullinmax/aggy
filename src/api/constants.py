from config import config
from datetime import timedelta

SOURCES_TO_INGEST_KEY = "SOURCE-KEYS-TO-INGEST"
SOURCE_READ_INTERVAL_TIMEDELTA = timedelta(
    minutes=config.get("SOURCE_READ_INTERVAL_MINUTES")
)
