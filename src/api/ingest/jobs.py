from constants import FEEDS_TO_INGEST_KEY, FEED_CHECK_INTERVAL_TIMEDELTA
from db.base import get_db_con
from db.feed import Feed
from ingest.feed import ingest_feed
import logging
from datetime import datetime, timedelta

from db.user import User


def feed_ingestion_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for category in user.categories:
            for feed in category.feeds:
                feed.trigger_ingest(now=False)


def feed_ingestion_job() -> None:
    r = get_db_con()

    if not r.exists(FEEDS_TO_INGEST_KEY):
        return

    res = r.zmpop(1, [FEEDS_TO_INGEST_KEY], min=True)[1][0]
    feed_key, scheduled_time = res
    scheduled_time = datetime.fromtimestamp(int(scheduled_time))

    # if the feed isn't due yet
    if scheduled_time > datetime.now() + timedelta(minutes=1):
        # replace the feed without altering it
        # take the sooner of the values if a feed already exists
        r.zadd(
            FEEDS_TO_INGEST_KEY,
            mapping={feed_key: int(scheduled_time.timestamp())},
            lt=True,
        )
        return

    try:
        feed = Feed.read_by_key(feed_key=feed_key)
        ingest_feed(feed=feed)
    except Exception as e:
        logging.error(f"Ingesting of feed {feed_key} failed: {e}")
        return

    # reschedule the feed for next go-round
    next_process_time = scheduled_time + FEED_CHECK_INTERVAL_TIMEDELTA
    next_process_time = int(next_process_time.timestamp())
    r.zadd(FEEDS_TO_INGEST_KEY, mapping={feed_key: next_process_time}, lt=True)
