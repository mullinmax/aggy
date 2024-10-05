import logging

from constants import SOURCES_TO_INGEST_QUEUE, SOURCE_READ_INTERVAL_TIMEDELTA
from db.source import Source
from ingest.source import ingest_source
from db.user import User
from utils import get_ollama_connection, schedule, scheduled_keys
from config import config


def source_ingestion_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for feed in user.feeds:
            for source in feed.sources:
                schedule(
                    queue=SOURCES_TO_INGEST_QUEUE,
                    key=source.key,
                    interval=SOURCE_READ_INTERVAL_TIMEDELTA,
                )


def source_ingestion_job() -> None:
    for source_key in scheduled_keys(
        queue=SOURCES_TO_INGEST_QUEUE, interval=SOURCE_READ_INTERVAL_TIMEDELTA
    ):
        if source_key is None:
            return
        try:
            source = Source.read_by_key(source_key=source_key)
            ingest_source(source=source)
        except Exception as e:
            logging.error(f"Ingesting of source {source_key} failed: {e}")
            return


def download_embedding_model_job() -> None:
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)

    if embedding_model is None:
        return

    ollama = get_ollama_connection()

    models = ollama.list()
    if embedding_model not in models:
        ollama.pull(embedding_model)
