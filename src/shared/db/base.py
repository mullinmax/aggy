from pydantic import BaseModel, HttpUrl
from typing import Any, Dict
from datetime import datetime, date
import functools
import redis

from ..config import config

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