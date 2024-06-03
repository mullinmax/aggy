from pydantic import BaseModel, HttpUrl
from typing import Dict, Any, Optional, List
from db.base import get_db_con


class FeedTemplateParameter(BaseModel):
    name: str
    required: bool
    type: str
    default: Optional[Any] = None
    placeholder: Optional[str] = None
    title: Optional[str] = None
    options: Optional[Dict[str, str]] = None


class FeedTemplate(BaseModel):
    name: str
    uri: HttpUrl
    description: str
    context: str
    parameters: Dict[str, FeedTemplateParameter]

    @property
    def key(self):
        return f"FEED_TEMPLATE:{self.name}"

    def save(self):
        with get_db_con() as r:
            r.set(self.key, self.json())

    @classmethod
    def get(cls, name: str):
        key = f"FEED_TEMPLATE:{name}"
        with get_db_con() as r:
            data = r.get(key)
            if data:
                return cls.parse_raw(data)
            return None

    @classmethod
    def get_all(cls) -> List["FeedTemplate"]:
        templates = []
        with get_db_con() as r:
            keys = r.keys("FEED_TEMPLATE:*")
            for key in keys:
                data = r.get(key)
                if data:
                    templates.append(cls.parse_raw(data))
        return templates
