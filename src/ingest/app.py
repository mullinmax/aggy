from datetime import datetime, timedelta
import logging
from concurrent.futures import ThreadPoolExecutor
import time
import os
import redis

from parse_feed import parse_feed

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = int(os.getenv('REDIS_PORT'))
EXTRACT_HOST = os.getenv('EXTRACT_HOST')
EXTRACT_PORT = int(os.getenv('EXTRACT_PORT'))
INGEST_NUM_THREADS = int(os.getenv('INGEST_NUM_THREADS'))

FEEDS_TO_INGEST_KEY = 'FEEDS-TO-INGEST'
FEED_INGESTION_PERIOD = 1800


def build_feed_to_ingest_list():
    logging.info(f'building FEEDS-TO-INGEST list')
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # read in each user
    user_keys = r.smembers('USERS')
    for user_key in user_keys:
        # read in each feed from each user
        feed_keys = r.smembers(f"{user_key}:FEEDS")
        target_time = (datetime.now() + timedelta(seconds=FEED_INGESTION_PERIOD)).timestamp()
        r.zadd(
            FEEDS_TO_INGEST_KEY, 
            mapping={feed_key: target_time for feed_key in feed_keys},
            lt=True #take the sooner of the values if a feed already exists
        )
    logging.info(f'FEEDS-TO-INGEST build complete')

def parse_next_feed():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # get the lowest scoring (ie soonest required) feed from FEEDS-TO-INGEST
    feed_key, target_time = r.zpopmin(FEEDS_TO_INGEST_KEY)
    logging.info(f'processing feed {feed_key} with target_time {target_time}')
    target_time = datetime.fromtimestamp(target_time)
    # if the feed isn't supposed to be read for another full minute
    if target_time > datetime.now() + timedelta(minutes=1):
        # put the feed back without altering it
        r.zadd(
            FEEDS_TO_INGEST_KEY, 
            mapping={feed_key: target_time},
            lt=True #take the sooner of the values if a feed already exists
        )
        return

    # update the feed read time for next go-round
    r.zadd(
        FEEDS_TO_INGEST_KEY, 
        mapping={feed_key: (datetime.now() + timedelta(seconds=FEED_INGESTION_PERIOD)).timestamp()},
        lt=True #take the sooner of the values if a feed already exists
    )
    
    # parse the feed
    parse_feed(feed_key)

if __name__ == "__main__":
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    executor = ThreadPoolExecutor(max_workers=INGEST_NUM_THREADS)
    
    last_feeds_to_ingest_build_timestamp = datetime.now()
    while(True):
        # occasionally build/repair the FEEDS-TO-INGEST list
        if last_feeds_to_ingest_build_timestamp < datetime.now():
            executor.submit(build_feed_to_ingest_list)
            last_feeds_to_ingest_build_timestamp = datetime.now() + timedelta(seconds=3600)
        
        # check if there's a feed that needs to be read
        
        res = r.zrange(FEEDS_TO_INGEST_KEY, 0, 0, withscores=True)
        logging.info(res)
        if res is not None and len(res) > 0:
            target_time = datetime.fromtimestamp(res[0][1])
            logging.info(f'target time is {target_time.strftime("%a %d %b %Y, %I:%M%p")}')
            logging.info(f'which is in {target_time - datetime.now()}')
            if target_time < datetime.now() + timedelta(minutes=1):
                logging.info('Processing next feed')
                executor.submit(parse_next_feed)
            else:
                time.sleep(5)
        time.sleep(10)