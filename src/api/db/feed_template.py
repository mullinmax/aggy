from pydantic import HttpUrl
from typing import Dict, Any, Optional, List

from db.base import BlinderBaseModel
from config import config


class FeedTemplateParameter(BlinderBaseModel):
    name: str
    required: bool
    type: str  # TODO: Enum
    default: Optional[Any] = None
    example: Optional[str] = None
    title: Optional[str] = None
    options: Optional[Dict[str, str]] = None


class FeedTemplate(BlinderBaseModel):
    name: str
    bridge_short_name: Optional[str] = None
    url: HttpUrl
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

    def create_rss_url(self, **kwargs) -> str:
        # TODO validate parameters
        # TODO use url encoding
        url = f"http://{config.get('RSS_BRIDGE_HOST')}:{config.get('RSS_BRIDGE_PORT')}/?action=display&bridge={self.bridge_short_name}"

        if self.context:
            url += f"&context={self.context}"

        for name, parameter in self.parameters.items():
            if name in kwargs:
                url += f"&{name}={kwargs[name]}"
            # TODO enforce required parameters
            elif parameter.default is not None:
                url += f"&{name}={parameter.default}"

        url += "&format=Atom"
        return url

    def create(self):
        with self.db_con() as r:
            r.set(self.key, self.model_dump_json())

    @classmethod
    def read(cls, name_hash: str) -> Optional["FeedTemplate"]:
        with cls.db_con() as r:
            data = r.get(f"FEED_TEMPLATE:{name_hash}")
            if data:
                return cls.model_validate_json(data)
            return None

    @classmethod
    def read_all(cls) -> List["FeedTemplate"]:
        templates = []
        with cls.db_con() as r:
            keys = r.keys("FEED_TEMPLATE:*")
            for key in keys:
                template = cls.read(key.split(":")[1])
                if template:
                    templates.append(template)
        return templates
