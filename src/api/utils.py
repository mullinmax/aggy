from ollama import Client
from httpx import BasicAuth
from datetime import datetime, timedelta

from config import config
from db.base import get_db_con


def get_ollama_connection() -> Client:
    ollama_args = {"host": config.get("OLLAMA_HOST") + ":" + config.get("OLLAMA_PORT")}

    auth_user = config.get("OLLAMA_USER", False)
    auth_password = config.get("OLLAMA_PASSWORD", False)
    if auth_user and auth_password:
        ollama_args["auth"] = BasicAuth(username=auth_user, password=auth_password)

    ollama = Client(**ollama_args)

    return ollama


def skip_limit_to_start_end(skip: int = 0, limit: int = -1) -> tuple[int, int]:
    """Converts a skip and limit to a start and end index."""
    start = 0
    if skip is not None and skip > 0:
        start = skip

    end = -1
    if limit is not None and limit >= 0:
        end = start + limit - 1

    return (start, end)


def schedule(
    queue: str,
    key: str,
    interval: timedelta = None,
    now: bool = False,
    at: datetime = None,
):
    """Schedule a key to be processed in the future."""

    if now and at:
        raise ValueError("Cannot specify both now and at when scheduling a task.")

    if at:
        when = at
    elif now:
        when = datetime.now()
    elif interval is None:
        raise ValueError(
            "Must specify at least one of now, or at, or interval when scheduling a task."
        )
    else:
        when = datetime.now() + interval

    r = get_db_con()
    # lt=True means that if the source is already in the list
    # it will only be updated if the new "when" is lower (sooner)
    r.zadd(queue, mapping={key: int(when.timestamp())}, lt=True)


def scheduled_keys(
    queue: str,
    interval: timedelta,
    window: timedelta = timedelta(seconds=60),
    reschedule=True,
):
    """Generator that yields the next key to be processed from the queue."""
    r = get_db_con()
    while True:
        if not r.exists(queue):
            return

        key, scheduled_time = r.zmpop(1, [queue], min=True)[1][0]
        scheduled_time = datetime.fromtimestamp(int(scheduled_time))

        # if the key isn't due yet, put it back in the queue
        if scheduled_time > datetime.now() + window:
            schedule(queue, key, at=scheduled_time)
            return
        else:
            yield key

        # Reschedule the key after processing
        if reschedule:
            schedule(queue, key, interval=interval, at=scheduled_time + interval)
