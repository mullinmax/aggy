from pydantic import BaseModel
import redis
from contextlib import contextmanager

from ..config import config


def get_redis_con():
    r = redis.Redis(
        host=config.get("REDIS_HOST"),
        port=int(config.get("REDIS_PORT")),
        decode_responses=True,
        db=0,
    )
    return r


class BlinderBaseModel(BaseModel):
    @property
    def key(self):
        raise NotImplementedError()

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
        """Context manager to handle Redis connections."""
        r = get_redis_con()
        yield r
