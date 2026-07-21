from pydantic import BaseModel
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
import hashlib
import base64
import json
import threading

from config import config

# Make JSON/JSONB columns come back as parsed Python objects.
psycopg2.extras.register_default_json(loads=json.loads, globally=True)
psycopg2.extras.register_default_jsonb(loads=json.loads, globally=True)


_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    host=config.get("DB_HOST"),
                    port=int(config.get("DB_PORT")),
                    user=config.get("DB_USER"),
                    password=config.get("DB_PASSWORD"),
                    dbname=config.get("DB_NAME"),
                )
    return _pool


@contextmanager
def get_db_con():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
    finally:
        pool.putconn(conn)


class AggyBaseModel(BaseModel):
    @property
    def key(self):
        raise NotImplementedError()

    @property
    def as_dict(self) -> dict:
        return json.loads(self.json())

    @property
    def json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def __insecure_hash__(cls, txt: str):
        raw_hash = hashlib.blake2b(txt.encode(), digest_size=32).digest()
        base_64_hash = base64.urlsafe_b64encode(raw_hash)
        return base_64_hash.decode("utf-8").rstrip("=")

    def exists(self) -> bool:
        raise NotImplementedError()

    def create(self, overwrite=False):
        raise NotImplementedError()

    def delete(self):
        raise NotImplementedError()

    @classmethod
    @contextmanager
    def db_con(cls):
        with get_db_con() as cur:
            yield cur

    # enable truthiness for objects if len is defined and sometimes 0
    def __bool__(self):
        return True

    def __str__(self):
        return self.json

    def __repr__(self):
        return self.__str__()


# Tables managed by Flyway. Listed for use by the test/dev flush helper.
_ALL_TABLES = (
    "ranking_model_stats",
    "list_items",
    "lists",
    "item_states",
    "source_items",
    "feed_items",
    "items",
    "sources",
    "feeds",
    "users",
    "source_templates",
)


def db_init(flush: bool = False) -> None:
    """Verify connectivity to Postgres. Optionally truncate all aggy tables.

    Schema is owned by Flyway; this function only checks the connection
    is healthy and (when ``flush`` is set) wipes the data for tests.
    """
    with get_db_con() as cur:
        cur.execute("SELECT 1")
        if flush:
            cur.execute(
                "TRUNCATE TABLE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(_ALL_TABLES)
                )
            )
