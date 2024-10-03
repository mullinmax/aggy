from ollama import Client
from httpx import BasicAuth
from datetime import datetime, timedelta
from contextlib import contextmanager

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
    que: str, key: str, interval: timedelta, now: bool = False, at: datetime = None
):
    """Schedule a key to be processed in the future."""

    if now and at:
        raise ValueError("Cannot specify both now and at when scheduling a task.")

    if at is not None:
        when = at
    elif now:
        when = datetime.now()
    else:
        when = datetime.now() + interval

    r = get_db_con()
    # lt=True means that if the source is already in the list
    # it will only be updated if the new "when" is lower (sooner)
    r.zadd(que, mapping={key: int(when.timestamp())}, lt=True)


# context manager to enable getting the next item from a queue
# and then rescheduling it
@contextmanager
def next_scheduled_key(
    que: str,
    interval: timedelta,
    window: timedelta = timedelta(seconds=60),
    reschedule=True,
):
    r = get_db_con()
    if not r.exists(que):
        return

    key, scheduled_time = r.zmpop(1, [que], min=True)[1][0]
    scheduled_time = datetime.fromtimestamp(int(scheduled_time))

    # if the source isn't due yet put it back in the queue
    if scheduled_time <= datetime.now() + window:
        schedule(que, key, at=scheduled_time)
        return

    yield key

    if reschedule:
        schedule(que, key, at=scheduled_time + interval)
