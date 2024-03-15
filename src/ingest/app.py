from datetime import datetime, timedelta
import logging
import time
import traceback

from parse_feed import parse_feed
from shared.config import config
from shared import db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def build_feed_to_ingest_list():
    logging.info("building FEED-KEYS-TO-INGEST list")
    r = db.r
    # read in each user
    user_hashes = r.smembers("USERS")
    for user_hash in user_hashes:
        logging.info(f"collecting feeds from user: {user_hash}")
        # read in each feed from each user
        feed_hashes = r.smembers(f"USER:{user_hash}:FEEDS")
        logging.info(f"user: {user_hash} feed_hashes: {feed_hashes}")
        if len(feed_hashes) > 0:
            target_time = (
                datetime.now() + timedelta(seconds=config.get("FEED_INGESTION_PERIOD"))
            ).timestamp()
            r.zadd(
                config.get("FEEDS_TO_INGEST_KEY"),
                mapping={
                    f"USER:{user_hash}:FEED:{feed_hash}": target_time
                    for feed_hash in feed_hashes
                },
                lt=True,  # take the sooner of the values if a feed already exists
            )
    logging.info("FEED-KEYS-TO-INGEST build complete")


def parse_next_feed():
    r = db.r
    # get the lowest scoring (ie soonest required) feed from FEED-KEYS-TO-INGEST
    res = r.zmpop(1, [config.get("FEEDS_TO_INGEST_KEY")], min=True)[1][0]
    logging.info(f"result of poping min: {res}")
    feed_key, target_time = res
    logging.info(f"processing feed {feed_key} with target_time {target_time}")
    target_time = datetime.fromtimestamp(float(target_time))
    # if the feed isn't supposed to be read for another full minute
    if target_time > datetime.now() + timedelta(minutes=1):
        logging.info("this feed is not quite ripe")
        # put the feed back without altering it
        r.zadd(
            config.get("FEEDS_TO_INGEST_KEY"),
            mapping={feed_key: target_time},
            lt=True,  # take the sooner of the values if a feed already exists
        )
        return

    # parse the feed
    parse_feed(feed_key)

    # update the feed read time for next go-round
    r.zadd(
        config.get("FEEDS_TO_INGEST_KEY"),
        mapping={
            feed_key: (
                datetime.now() + timedelta(seconds=config.get("FEED_INGESTION_PERIOD"))
            ).timestamp()
        },
        lt=True,  # take the sooner of the values if a feed already exists
    )


if __name__ == "__main__":
    r = db.r
    # executor = ThreadPoolExecutor(max_workers=INGEST_NUM_THREADS)

    # with ThreadPoolExecutor(max_workers=INGEST_NUM_THREADS) as executor:
    last_feeds_to_ingest_build_timestamp = datetime.now()
    while True:
        # occasionally build/repair the FEEDS-TO-INGEST list
        if last_feeds_to_ingest_build_timestamp < datetime.now():
            # executor.submit(build_feed_to_ingest_list)
            try:
                build_feed_to_ingest_list()
            except Exception as e:
                logging.error(e)
                logging.error(traceback.format_exc())
            last_feeds_to_ingest_build_timestamp = datetime.now() + timedelta(
                seconds=3600
            )

        # check if there's a feed that needs to be read

        res = r.zrange(config.get("FEEDS_TO_INGEST_KEY"), 0, 0, withscores=True)
        logging.info(f"next feed to ingest: {res}")
        if res is not None and len(res) > 0:
            target_time = datetime.fromtimestamp(res[0][1])
            logging.info(
                f'target time is {target_time.strftime("%a %d %b %Y, %I:%M%p")}'
            )
            logging.info(f"which is in {target_time - datetime.now()}")
            if target_time < datetime.now() + timedelta(minutes=1):
                logging.info("Processing next feed")
                # executor.submit(parse_next_feed)
                try:
                    parse_next_feed()
                except Exception as e:
                    logging.error(e)
                    logging.error(traceback.format_exc())
            else:
                time.sleep(5)
        time.sleep(10)
