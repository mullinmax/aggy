from pydantic import BaseModel
import functools
import redis

from shared.config import config

r = redis.Redis(
    host=config.get('REDIS_HOST'), 
    port=int(config.get('REDIS_PORT')), 
    decode_responses=True, 
    db=0
)

class BlinderBaseModel(BaseModel):
    @functools.cached_property
    def r(self):
        return r