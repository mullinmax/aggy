import logging
from datetime import datetime, timedelta

from constants import SOURCES_TO_INGEST_KEY, SOURCE_READ_INTERVAL_TIMEDELTA
from db.base import get_db_con
from db.source import Source
from ingest.source import ingest_source
from db.user import User
from utils import get_ollama_connection
from config import config


def source_ingestion_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for feed in user.feeds:
            for source in feed.sources:
                source.trigger_ingest(now=False)


def source_ingestion_job() -> None:
    r = get_db_con()

    if not r.exists(SOURCES_TO_INGEST_KEY):
        return

    res = r.zmpop(1, [SOURCES_TO_INGEST_KEY], min=True)[1][0]
    source_key, scheduled_time = res
    scheduled_time = datetime.fromtimestamp(int(scheduled_time))

    # if the source isn't due yet
    if scheduled_time > datetime.now() + timedelta(minutes=1):
        # replace the source without altering it
        # take the sooner of the values if a source already exists
        r.zadd(
            SOURCES_TO_INGEST_KEY,
            mapping={source_key: int(scheduled_time.timestamp())},
            lt=True,
        )
        return

    try:
        source = Source.read_by_key(source_key=source_key)
        ingest_source(source=source)
    except Exception as e:
        logging.error(f"Ingesting of source {source_key} failed: {e}")
        return

    # reschedule the source for next go-round
    next_process_time = scheduled_time + SOURCE_READ_INTERVAL_TIMEDELTA
    next_process_time = int(next_process_time.timestamp())
    r.zadd(SOURCES_TO_INGEST_KEY, mapping={source_key: next_process_time}, lt=True)


def download_embedding_model_job() -> None:
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)

    if embedding_model is None:
        return

    ollama = get_ollama_connection()

    models = ollama.list()
    if embedding_model not in models:
        ollama.pull(embedding_model)
