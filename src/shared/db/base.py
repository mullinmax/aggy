from pydantic import BaseModel, HttpUrl
from typing import Any, Dict
from datetime import datetime, date
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
    def str_dict(self, *args, **kwargs) -> Dict[str, Any]:
        d = super().dict(*args, **kwargs)

        # Convert fields to appropriate format for Redis
        for key, value in d.items():
            if isinstance(value, (datetime, date)):
                # Convert datetime/date to ISO 8601 string format
                d[key] = value.isoformat()
            elif isinstance(value, HttpUrl):
                # Convert HttpUrl to string
                d[key] = str(value)
            # Add handling for other types as necessary

        return d

    @property
    def key(self):
        raise NotImplementedError()
