from pydantic import HttpUrl

from .base import BaseRouteModel
from db.feed_template import FeedTemplate


class FeedTemplateParameterRouteModel(BaseRouteModel):
    name: str
    required: bool
    type: str
    default: str
    placeholder: str
    title: str
    options: dict


class FeedTemplateRouteModel(BaseRouteModel):
    name: str
    bridge_short_name: str
    url: HttpUrl
    description: str
    context: str
    parameters: dict

    @classmethod
    def from_db_model(cls, db_model: FeedTemplate):
        return cls(
            name=db_model.name,
            bridge_short_name=db_model.bridge_short_name,
            url=db_model.url,
            description=db_model.description,
            context=db_model.context,
            parameters=db_model.parameters,
        )
