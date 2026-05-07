import logging
from datetime import datetime, timedelta

from constants import SOURCE_READ_INTERVAL_TIMEDELTA
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
    """Pop the next due source and ingest it.

    Mirrors the previous Redis ZMPOP-based queue: pick the source with the
    smallest ``next_ingest_at``, only proceed if it's actually due, and then
    bump its next ingest time forward.
    """
    cutoff = datetime.now() + timedelta(minutes=1)

    with get_db_con() as cur:
        cur.execute(
            "SELECT user_hash, feed_hash, name_hash, next_ingest_at "
            "FROM sources WHERE next_ingest_at <= %s "
            "ORDER BY next_ingest_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
            (cutoff,),
        )
        row = cur.fetchone()

        if not row:
            return

        next_run = row["next_ingest_at"] + SOURCE_READ_INTERVAL_TIMEDELTA
        cur.execute(
            "UPDATE sources SET next_ingest_at = %s "
            "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
            (next_run, row["user_hash"], row["feed_hash"], row["name_hash"]),
        )

    try:
        source = Source.read(
            user_hash=row["user_hash"],
            feed_hash=row["feed_hash"],
            source_hash=row["name_hash"],
        )
        ingest_source(source=source)
    except Exception as e:
        logging.exception(f"Ingesting of source {row['name_hash']} failed: {e}")
        return


def download_embedding_model_job() -> None:
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)

    if embedding_model is None:
        return

    ollama = get_ollama_connection()

    models = ollama.list()
    if embedding_model not in models:
        ollama.pull(embedding_model)
