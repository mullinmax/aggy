from pydantic import BaseModel
import redis
from redislite import Redis as redis_lite

from ..config import config


def get_redis_connection():
    if config.get("TESTING_MODE"):
        return redis_lite()

    return redis.Redis(
        host=config.get("REDIS_HOST"),
        port=int(config.get("REDIS_PORT")),
        decode_responses=True,
        db=0,
    )


r = get_redis_connection()


class BlinderBaseModel(BaseModel):
    @property
    def key(self):
        raise NotImplementedError()
