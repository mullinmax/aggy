from pydantic import HttpUrl
from typing import Dict, Any, Optional, List, Union
from enum import Enum
import urllib
import json
from rapidfuzz import fuzz

from db.base import AggyBaseModel
from config import config
from utils import skip_limit_to_start_end


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
                if parameter.required:
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

    def exists(self) -> bool:
        with self.db_con() as cur:
            cur.execute(
                "SELECT 1 FROM source_templates WHERE name_hash = %s",
                (self.name_hash,),
            )
            return cur.fetchone() is not None

    def create(self):
        params_json = json.dumps(
            {k: json.loads(v.model_dump_json()) for k, v in self.parameters.items()}
        )
        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO source_templates (name_hash, name, bridge_short_name, "
                "url, description, context, parameters) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (name_hash) DO UPDATE SET "
                "name = EXCLUDED.name, "
                "bridge_short_name = EXCLUDED.bridge_short_name, "
                "url = EXCLUDED.url, description = EXCLUDED.description, "
                "context = EXCLUDED.context, parameters = EXCLUDED.parameters",
                (
                    self.name_hash,
                    self.name,
                    self.bridge_short_name,
                    str(self.url),
                    self.description,
                    self.context,
                    params_json,
                ),
            )

    def delete(self):
        with self.db_con() as cur:
            cur.execute(
                "DELETE FROM source_templates WHERE name_hash = %s",
                (self.name_hash,),
            )

    @classmethod
    def _from_row(cls, row) -> "SourceTemplate":
        params_raw = row["parameters"]
        if isinstance(params_raw, str):
            params_raw = json.loads(params_raw)
        parameters = {
            k: SourceTemplateParameter(**v) for k, v in (params_raw or {}).items()
        }
        return cls(
            name=row["name"],
            bridge_short_name=row["bridge_short_name"],
            url=row["url"],
            description=row["description"],
            context=row["context"],
            parameters=parameters,
        )

    @classmethod
    def read(cls, name_hash: str) -> Optional["SourceTemplate"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name, bridge_short_name, url, description, context, "
                "parameters FROM source_templates WHERE name_hash = %s",
                (name_hash,),
            )
            row = cur.fetchone()

        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    def read_all(cls) -> List["SourceTemplate"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name, bridge_short_name, url, description, context, "
                "parameters FROM source_templates"
            )
            rows = cur.fetchall()

        return [cls._from_row(row) for row in rows]

    @classmethod
    def search(
        cls, query: str, skip: Union[int, None] = None, limit: Union[int, None] = None
    ) -> List["SourceTemplate"]:
        templates = cls.read_all()

        scored = [(t, fuzz.ratio(query.lower(), t.name.lower())) for t in templates]
        scored.sort(key=lambda x: x[1], reverse=True)

        start, end = skip_limit_to_start_end(skip, limit)
        if end == -1:
            paginated = scored[start:]
        else:
            paginated = scored[start : end + 1]

        return [t for t, _ in paginated]
