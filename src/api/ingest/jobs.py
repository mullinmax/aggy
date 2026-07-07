import logging

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

    All time comparison happens in SQL so it is done against the database
    clock; ``next_ingest_at`` is a TIMESTAMPTZ and comparing it to a naive
    Python ``datetime.now()`` silently pushes ingestion hours into the
    future whenever the app and database timezones differ.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT user_hash, feed_hash, name_hash FROM sources "
            "WHERE next_ingest_at <= NOW() + interval '1 minute' "
            "ORDER BY next_ingest_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
        row = cur.fetchone()

        if not row:
            return

        cur.execute(
            "UPDATE sources SET next_ingest_at = NOW() + %s "
            "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
            (
                SOURCE_READ_INTERVAL_TIMEDELTA,
                row["user_hash"],
                row["feed_hash"],
                row["name_hash"],
            ),
        )

    source = None
    try:
        source = Source.read(
            user_hash=row["user_hash"],
            feed_hash=row["feed_hash"],
            source_hash=row["name_hash"],
        )
        logging.info(f"Ingesting source '{source.name}' ({source.url})")
        ingest_source(source=source)
        source.mark_ingested()
    except Exception as e:
        logging.exception(f"Ingesting of source {row['name_hash']} failed: {e}")
        if source is not None:
            source.mark_ingest_error(str(e))
        return


def ingest_source_now(source: Source) -> None:
    """Ingest a freshly-added source immediately (outside the schedule).

    Pushes the next scheduled run out first so the interval job doesn't
    double-ingest, then runs the ingest inline.
    """
    source.push_next_ingest()
    try:
        logging.info(f"Ingesting new source '{source.name}' ({source.url})")
        ingest_source(source=source)
        source.mark_ingested()
    except Exception as e:
        logging.exception(f"Initial ingest of source '{source.name}' failed: {e}")
        source.mark_ingest_error(str(e))


def download_embedding_model_job() -> None:
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)

    if embedding_model is None:
        return

    ollama = get_ollama_connection()

    models = ollama.list()
    if embedding_model not in models:
        ollama.pull(embedding_model)
