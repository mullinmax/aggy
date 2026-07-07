from config import config
from datetime import timedelta

SOURCE_READ_INTERVAL_TIMEDELTA = timedelta(
    minutes=config.get_int("SOURCE_READ_INTERVAL_MINUTES")
)
