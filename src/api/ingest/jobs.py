from constants import FEEDS_TO_INGEST_KEY, FEED_CHECK_INTERVAL_TIMEDELTA
from db.base import get_db_con
from db.feed import Feed
from ingest.feed import ingest_feed
import logging
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

from config import config
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
        r.zadd(FEEDS_TO_INGEST_KEY, mapping={feed_key: scheduled_time}, lt=True)
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


def rss_bridge_get_templates_job() -> None:
    if config.get("RSS_BRIDGE_HOST") is None:
        logging.info("RSS_BRIDGE_HOST is not set in the config")

    try:
        # Ensure the URL includes the scheme
        host = config.get("RSS_BRIDGE_HOST")
        port = config.get("RSS_BRIDGE_PORT")

        # Check if the host starts with http or https, otherwise default to http
        if not host.startswith("http://") and not host.startswith("https://"):
            host = "http://" + host

        url = f"{host}:{port}/"

        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        soup = BeautifulSoup(response.content, "html.parser")
        bridge_list = {}

        # Find all bridge elements
        for bridge in soup.find_all("section", class_="bridge-card"):
            bridge_name = bridge.find("h2").text.strip()
            bridge_uri = bridge.find("a", href=True)["href"]
            bridge_description = bridge.find("p", class_="description").text.strip()
            bridge_parameters = {}

            # Find all parameter groups
            for param_group in bridge.find_all("div", class_="input-container"):
                group_name = param_group.find("span", class_="title").text.strip()
                bridge_parameters[group_name] = {}

                # Find all parameters within the group
                for param in param_group.find_all("div", class_="input"):
                    param_name = param.find("span", class_="paramname").text.strip()
                    param_info = {
                        "name": param_name,
                        "required": "required" in param.find("input").attrs,
                        "title": param.find("span", class_="desc").text.strip(),
                    }
                    bridge_parameters[group_name][param_name] = param_info

            bridge_list[bridge_name] = {
                "uri": bridge_uri,
                "description": bridge_description,
                "parameters": bridge_parameters,
            }

        logging.info(f"RSS bridge templates: {bridge_list}")
    except Exception as e:
        logging.error(f"Failed to get RSS bridge templates: {e}")
        return None
