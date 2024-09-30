from pydantic import HttpUrl
from typing import Dict, Any, Optional, List
from enum import Enum
import urllib

from db.base import AggyBaseModel
from config import config


class SourceTemplateParameterType(Enum):
    text = "text"
    select = "select"
    checkbox = "checkbox"
    number = "number"


class SourceTemplateParameter(AggyBaseModel):
    name: str
    required: bool
    type: SourceTemplateParameterType
    default: Optional[Any] = None
    example: Optional[str] = None
    title: Optional[str] = None
    options: Optional[Dict[str, str]] = None


class SourceTemplate(AggyBaseModel):
    name: str
    bridge_short_name: Optional[str] = None
    url: HttpUrl
    description: str
    context: Optional[str] = None
    parameters: Dict[str, SourceTemplateParameter]

    @property
    def key(self):
        return f"SOURCE_TEMPLATE:{self.name_hash}"

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.user_friendly_name)

    @property
    def user_friendly_name(self):
        if self.context:
            return f"{self.name} ({self.context})"
        return self.name

    def validate_parameters(self, **kwargs) -> None:
        validation_issues = []

        for name, parameter in self.parameters.items():
            if name in kwargs and kwargs[name] is not None:
                if (
                    parameter.options is not None
                    and kwargs[name] not in parameter.options
                ):
                    validation_issues.append(
                        f"Parameter {name} must be one of {list(parameter.options.keys())}"
                    )
            else:
                if parameter.required or parameter.default is None:
                    validation_issues.append(f"Parameter {name} is required")
                elif (
                    parameter.default is not None
                    and parameter.options is not None
                    and parameter.default not in parameter.options
                ):
                    validation_issues.append(
                        f"Parameter {name} must be one of {list(parameter.options.keys())}"
                    )

        for name, value in kwargs.items():
            # all parameters must be defined in the template
            if name not in self.parameters:
                validation_issues.append(
                    f"Parameter {name} is not defined in the template"
                )

        if validation_issues:
            raise Exception(f"Validation issues: {', '.join(validation_issues)}")

    def create_rss_url(self, **kwargs) -> str:
        if kwargs is None:
            kwargs = {}

        self.validate_parameters(**kwargs)

        url_params = {
            "action": "display",
            "bridge": self.bridge_short_name,
            "format": "Atom",
        }

        if self.context:
            url_params["context"] = self.context

        for name, parameter in self.parameters.items():
            if name in kwargs:
                url_params[name] = kwargs[name]
            elif parameter.default is not None:
                url_params[name] = parameter.default

        return "http://{host}:{port}/?{query}".format(
            host=config.get("RSS_BRIDGE_HOST"),
            port=config.get("RSS_BRIDGE_PORT"),
            query=urllib.parse.urlencode(url_params),
        )

    def create(self):
        with self.db_con() as r:
            r.set(self.key, self.json)

            # add to list of all templates
            r.sadd("SOURCE_TEMPLATES", self.name_hash)

    @classmethod
    def read(cls, name_hash: str) -> Optional["SourceTemplate"]:
        with cls.db_con() as r:
            data = r.get(f"SOURCE_TEMPLATE:{name_hash}")
            if data:
                return cls.model_validate_json(data)
            return None

    @classmethod
    def read_all(cls) -> List["SourceTemplate"]:
        templates = []
        with cls.db_con() as r:
            template_hashes = r.smembers("SOURCE_TEMPLATES")
            for template_hash in template_hashes:
                template = cls.read(template_hash)
                if template:
                    templates.append(template)
        return templates
