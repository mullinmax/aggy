from pydantic import BaseModel
import redis
from contextlib import contextmanager
import logging
import hashlib
import base64

from ..config import config


def get_redis_con():
    return redis.Redis(
        host=config.get("REDIS_HOST"),
        port=int(config.get("REDIS_PORT")),
        decode_responses=True,
        db=0,
    )


class BlinderBaseModel(BaseModel):
    @property
    def key(self):
        raise NotImplementedError()

    @classmethod
    def __insecure_hash__(cls, txt: str):
        raw_hash = hashlib.blake2b(txt.encode(), digest_size=32).digest()
        base_64_hash = base64.urlsafe_b64encode(raw_hash)
        return base_64_hash.decode("utf-8").rstrip("=")

    def exists(self) -> bool:
        with self.redis_con() as r:
            return bool(r.exists(self.key))

    def create(self, overwrite=False):
        raise NotImplementedError()

    def delete(self):
        with self.redis_con() as r:
            r.delete(self.key)

    @classmethod
    @contextmanager
    def redis_con(cls):
        yield get_redis_con()


def db_init(flush=False):
    with get_redis_con() as r:
        if flush:
            r.flushdb()
        r.config_set("save", "60 1")  # TODO parameterize me
        try:
            r.config_rewrite()
        except redis.exceptions.ResponseError as e:
            logging.warning(f"Redis config write failed: {e}")
