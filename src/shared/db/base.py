from pydantic import BaseModel
import redis
from contextlib import contextmanager

from ..config import config

# r = redis.Redis(
#     host=config.get("REDIS_HOST"),
#     port=int(config.get("REDIS_PORT")),
#     decode_responses=True,
#     db=0,
# )


class BlinderBaseModel(BaseModel):
    @property
    def key(self):
        raise NotImplementedError()

    def exists(self) -> bool:
        with self.redis_con() as r:
            return bool(r.exists(self.key))

    def create(self, overwrite=False):
        raise NotImplementedError()

    @classmethod
    @contextmanager
    def redis_con(cls):
        """Context manager to handle Redis connections."""
        # Use actual Redis configuration for non-testing scenarios
        r = redis.Redis(
            host=config.get("REDIS_HOST"),
            port=int(config.get("REDIS_PORT")),
            decode_responses=True,
            db=0,
        )
        yield r
