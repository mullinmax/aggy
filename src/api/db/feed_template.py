from pydantic import HttpUrl
from typing import Dict, Any, Optional, List
from db.base import BlinderBaseModel


class FeedTemplateParameter(BlinderBaseModel):
    name: str
    required: bool
    type: str
    default: Optional[Any] = None
    placeholder: Optional[str] = None
    title: Optional[str] = None
    options: Optional[Dict[str, str]] = None


class FeedTemplate(BlinderBaseModel):
    name: str
    uri: HttpUrl
    description: str
    context: Optional[str] = None
    parameters: Dict[str, FeedTemplateParameter]

    @property
    def key(self):
        return f"FEED_TEMPLATE:{self.name_hash}"

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.user_friendly_name)

    @property
    def user_friendly_name(self):
        if self.context:
            return f"{self.name} ({self.context})"
        return self.name

    def create(self):
        with self.db_con() as r:
            r.set(self.key, self.json())

    @classmethod
    def read(cls, name_hash: str):
        with cls.db_con() as r:
            data = r.get(f"FEED_TEMPLATE:{name_hash}")
            if data:
                return cls.parse_raw(data)
            return None

    @classmethod
    def read_all(cls) -> List["FeedTemplate"]:
        templates = []
        with cls.db_con() as r:
            keys = r.keys("FEED_TEMPLATE:*")
            for key in keys:
                data = r.get(key)
                if data:
                    templates.append(cls.parse_raw(data))
        return templates
