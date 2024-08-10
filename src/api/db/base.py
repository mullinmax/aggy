from pydantic import BaseModel
import redis
from contextlib import contextmanager
import logging
import hashlib
import base64
import json

from config import config


def get_db_con():
    return redis.Redis(
        host=config.get("DB_HOST"),
        port=int(config.get("DB_PORT")),
        decode_responses=True,
        db=0,
    )


class BlinderBaseModel(BaseModel):
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
        with self.db_con() as r:
            return bool(r.exists(self.key))

    def create(self, overwrite=False):
        raise NotImplementedError()

    def delete(self):
        with self.db_con() as r:
            r.delete(self.key)

    @classmethod
    @contextmanager
    def db_con(cls):
        yield get_db_con()

    # enable truthiness for objects if len is defined and sometimes 0
    def __bool__(self):
        return True

    def __str__(self):
        return self.json

    def __repr__(self):
        return self.__str__()


def db_init(flush=False):
    with get_db_con() as r:
        if flush:
            r.flushdb()
        r.config_set("save", "60 1")  # TODO parameterize me
        try:
            r.config_rewrite()
        except redis.exceptions.ResponseError as e:
            logging.warning(f"Database config write failed: {e}")
