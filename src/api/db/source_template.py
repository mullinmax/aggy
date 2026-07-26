from pydantic import HttpUrl, computed_field
from typing import ClassVar, Dict, Any, Optional, List, Union
from enum import Enum
import urllib
import json
from rapidfuzz import fuzz

from constants import (
    PROVIDER_BUILTIN,
    PROVIDER_RANK,
    PROVIDER_RSSHUB,
    PROVIDER_RSS_BRIDGE,
    RSSHUB_TEMPLATE_PREFIX,
)
from db.base import AggyBaseModel
from config import config
from utils import skip_limit_to_start_end


def _escape(value: str, policy: str) -> str:
    if policy == "none":
        return value
    return urllib.parse.quote(value, safe="/" if policy == "path" else "")


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
    # How the value is escaped into a template's url_template:
    #   "strict" - a single value; everything but unreserved characters is
    #              encoded, so it can't escape its position in the URL
    #   "path"   - a path fragment ("github/issues/owner/repo"), so slashes
    #              survive encoding
    #   "none"   - the value IS a complete URL and is used verbatim (it is
    #              checked to be http(s) instead)
    quote: str = "strict"


class SourceTemplate(AggyBaseModel):
    name: str
    bridge_short_name: Optional[str] = None
    url: HttpUrl
    description: str
    context: Optional[str] = None
    parameters: Dict[str, SourceTemplateParameter]
    # Built-in (non-rss-bridge) templates: a python format string with
    # {parameter} placeholders, e.g. "https://www.reddit.com/r/{subreddit}/{sort}.rss"
    url_template: Optional[str] = None
    # Ingest backend the sources built from this template should use. "rss"
    # (the default) means the URL is fetched and parsed as a feed; see
    # ingest/backends for the rest.
    kind: str = "rss"

    @property
    def key(self):
        return f"SOURCE_TEMPLATE:{self.name_hash}"

    @computed_field  # serialized so API clients can reference templates by hash
    @property
    def name_hash(self) -> str:
        return self.__insecure_hash__(self.user_friendly_name)

    @computed_field
    @property
    def user_friendly_name(self) -> str:
        if self.context:
            return f"{self.name} ({self.context})"
        return self.name

    @computed_field
    @property
    def provider(self) -> str:
        """Which service produces this template's feed.

        Derived from what the template already carries rather than stored, so
        a re-import can't leave the label disagreeing with the template.
        """
        if not self.bridge_short_name:
            return PROVIDER_BUILTIN
        if self.bridge_short_name.startswith(RSSHUB_TEMPLATE_PREFIX):
            return PROVIDER_RSSHUB
        return PROVIDER_RSS_BRIDGE

    @computed_field
    @property
    def site_domain(self) -> str:
        """The site this template pulls from, e.g. "bilibili.com".

        Imported route names are often just "User posts", which says nothing
        about which site's users; the domain is what makes a result legible.
        """
        host = urllib.parse.urlparse(str(self.url)).netloc
        return host[4:] if host.startswith("www.") else host

    @computed_field
    @property
    def required_parameters(self) -> List[str]:
        """Names of the values a user must supply before this can be saved."""
        return [
            parameter.name or key
            for key, parameter in self.parameters.items()
            if parameter.required
        ]

    @computed_field
    @property
    def optional_parameter_count(self) -> int:
        return sum(1 for p in self.parameters.values() if not p.required)

    def validate_parameters(self, **kwargs) -> None:
        validation_issues = []

        for name, parameter in self.parameters.items():
            # empty strings count as missing: rss-bridge treats blank required
            # parameters as errors, which used to slip through and create
            # sources that could never ingest anything
            if name in kwargs and kwargs[name] is not None and kwargs[name] != "":
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
            # unescaped parameters go into the URL verbatim, so they have to
            # be a URL themselves rather than arbitrary text
            elif self.parameters[name].quote == "none" and value:
                if not str(value).lower().startswith(("http://", "https://")):
                    validation_issues.append(
                        f"Parameter {name} must be a http:// or https:// URL"
                    )

        if validation_issues:
            raise Exception(f"Validation issues: {', '.join(validation_issues)}")

    def create_source_url(self, **kwargs) -> str:
        """The URL a source built from this template should point at.

        For ``kind == "rss"`` that's a feed URL (rss-bridge's, or a site's own);
        for the other backends it's the page the backend goes on to work with.
        """
        if kwargs is None:
            kwargs = {}

        self.validate_parameters(**kwargs)

        # Built-in templates format their own URL directly instead of going
        # through rss-bridge.
        if self.url_template:
            values = {}
            for name, parameter in self.parameters.items():
                if name in kwargs and kwargs[name] not in (None, ""):
                    values[name] = kwargs[name]
                elif parameter.default is not None:
                    values[name] = parameter.default
            quoted = {
                k: _escape(str(v), self.parameters[k].quote) for k, v in values.items()
            }
            return self.url_template.format(**quoted)

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

    # Templates produced feed URLs exclusively before the other ingest
    # backends existed; keep the old name working for existing callers.
    create_rss_url = create_source_url

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
                "url, description, context, parameters, url_template, kind) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (name_hash) DO UPDATE SET "
                "name = EXCLUDED.name, "
                "bridge_short_name = EXCLUDED.bridge_short_name, "
                "url = EXCLUDED.url, description = EXCLUDED.description, "
                "context = EXCLUDED.context, parameters = EXCLUDED.parameters, "
                "url_template = EXCLUDED.url_template, kind = EXCLUDED.kind",
                (
                    self.name_hash,
                    self.name,
                    self.bridge_short_name,
                    str(self.url),
                    self.description,
                    self.context,
                    params_json,
                    self.url_template,
                    self.kind,
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
            url_template=row.get("url_template"),
            kind=row.get("kind") or "rss",
        )

    @classmethod
    def read(cls, name_hash: str) -> Optional["SourceTemplate"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name, bridge_short_name, url, description, context, "
                "parameters, url_template, kind FROM source_templates WHERE name_hash = %s",
                (name_hash,),
            )
            row = cur.fetchone()

        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    def read_by_bridge_short_name(
        cls, bridge_short_name: str
    ) -> Optional["SourceTemplate"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name, bridge_short_name, url, description, context, "
                "parameters, url_template, kind FROM source_templates "
                "WHERE bridge_short_name = %s LIMIT 1",
                (bridge_short_name,),
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
                "parameters, url_template, kind FROM source_templates"
            )
            rows = cur.fetchall()

        return [cls._from_row(row) for row in rows]

    # Matches scoring below this are dropped from search results, except that
    # the top SEARCH_MIN_RESULTS matches are always kept regardless of score.
    SEARCH_SCORE_THRESHOLD: ClassVar[int] = 50
    SEARCH_MIN_RESULTS: ClassVar[int] = 4

    @classmethod
    def search(
        cls,
        query: Union[str, None] = None,
        skip: Union[int, None] = None,
        limit: Union[int, None] = None,
    ) -> List["SourceTemplate"]:
        def browse_order(t: "SourceTemplate"):
            # Aggy's own handful of templates first, then rss-bridge, then
            # RSSHub's thousands — otherwise browsing is just RSSHub.
            return (PROVIDER_RANK.get(t.provider, 99), t.user_friendly_name.lower())

        templates = sorted(cls.read_all(), key=browse_order)
        query = (query or "").strip().lower()

        if query:

            def score(t: "SourceTemplate") -> float:
                # description matches are weighted below name matches so a
                # template whose name matches always outranks one where the
                # query only appears in the description. The provider and site
                # are matchable too, so "rsshub" or a bare domain both work.
                return max(
                    fuzz.WRatio(query, t.user_friendly_name.lower()),
                    fuzz.WRatio(query, t.site_domain.lower()),
                    fuzz.WRatio(query, t.provider.lower()),
                    fuzz.WRatio(query, (t.description or "").lower()) * 0.6,
                )

            # equal matches break toward the more reliable provider
            scored = sorted(
                ((t, score(t)) for t in templates),
                key=lambda x: (-x[1], PROVIDER_RANK.get(x[0].provider, 99)),
            )
            templates = [
                t
                for i, (t, s) in enumerate(scored)
                if s >= cls.SEARCH_SCORE_THRESHOLD or i < cls.SEARCH_MIN_RESULTS
            ]

        start, end = skip_limit_to_start_end(skip, limit)
        if end == -1:
            return templates[start:]
        return templates[start : end + 1]
