"""Import the bundled RSSHub instance's route catalog as source templates.

RSSHub is a second bridge next to rss-bridge: same idea (parameters in, a feed
out), a different and much larger set of sites. Its instance publishes every
route it knows at ``/api/namespace``, which maps cleanly onto Aggy's source
templates — so the routes become searchable in the same catalog as everything
else instead of the user having to hand-write route paths.

Imported templates are marked with a ``rsshub:`` prefix in
``bridge_short_name`` so they can be told apart from rss-bridge's — which is
what the catalog's provider label reads, and what lets them be cleaned up when
RSSHub goes away.
"""

import logging
import re
import urllib.parse
from typing import Optional

import requests

from config import config
from constants import RSSHUB_TEMPLATE_PREFIX as MARKER_PREFIX
from db.base import get_db_con
from db.source_template import SourceTemplate, SourceTemplateParameter

CATALOG_TIMEOUT_SECONDS = 60
# A route needing more than this many values is more of a form than a
# template; the generic "RSSHub Route" template still covers it.
MAX_ROUTE_PARAMETERS = 5

# ":name" and ":name?" path segments are RSSHub's route parameters.
_PARAMETER_PATTERN = re.compile(r":([A-Za-z0-9_]+)(\??)")


def is_configured() -> bool:
    return config.get("RSSHUB_HOST", None) is not None


def _base_url() -> str:
    return "http://{host}:{port}".format(
        host=config.get("RSSHUB_HOST"), port=config.get("RSSHUB_PORT")
    )


def _parameter_meta(raw, name: str) -> dict:
    """What the catalog says about one route parameter.

    RSSHub describes a parameter as either a bare description string or an
    object that can also carry a default and the values it accepts. Returns
    ``{description, default, options}`` with whatever was available.
    """
    meta = {"description": "", "default": None, "options": None}
    entry = raw.get(name) if isinstance(raw, dict) else None

    if isinstance(entry, str):
        meta["description"] = entry
        return meta
    if not isinstance(entry, dict):
        return meta

    meta["description"] = str(entry.get("description") or "")
    if entry.get("default") not in (None, ""):
        meta["default"] = str(entry["default"])

    options = entry.get("options")
    if isinstance(options, dict):
        meta["options"] = {str(k): str(v) for k, v in options.items()}
    elif isinstance(options, list):
        # [{value, label}, ...]
        pairs = {
            str(o["value"]): str(o.get("label") or o["value"])
            for o in options
            if isinstance(o, dict) and o.get("value") is not None
        }
        meta["options"] = pairs or None

    return meta


def _examples_from_route(namespace: str, path: str, example: str) -> dict:
    """Per-parameter example values, read out of the route's example URL.

    A route path like ``/user/:uid/:language?`` alongside the example
    ``/example/user/12345/en`` gives ``{"uid": "12345", "language": "en"}``.
    Without this a user has to guess what a segment wants, and a wrong guess
    is often accepted by the route and only fails when the feed is fetched.
    """
    if not example:
        return {}

    route_segments = f"/{namespace}{path}".strip("/").split("/")
    example_segments = example.strip("/").split("/")

    examples = {}
    for route_segment, example_segment in zip(route_segments, example_segments):
        match = _PARAMETER_PATTERN.fullmatch(route_segment)
        if match and example_segment:
            examples[match.group(1)] = urllib.parse.unquote(example_segment)
    return examples


def route_to_template(
    namespace: str, namespace_info: dict, path: str, route: dict
) -> Optional[SourceTemplate]:
    """One catalog route -> a source template, or None if it can't be one."""
    if "*" in path:
        # wildcard routes take a free-form remainder, which has no sensible
        # parameter form; the generic route template covers them
        return None

    matches = _PARAMETER_PATTERN.findall(path)
    if len(matches) > MAX_ROUTE_PARAMETERS:
        return None

    raw_parameters = route.get("parameters") or {}
    examples = _examples_from_route(namespace, path, str(route.get("example") or ""))

    parameters = {}
    for name, optional_marker in matches:
        meta = _parameter_meta(raw_parameters, name)
        options = meta["options"]
        parameters[name] = SourceTemplateParameter(
            name=name.replace("_", " ").title(),
            title=meta["description"],
            required=optional_marker != "?",
            # a parameter with a known set of values becomes a dropdown, so a
            # value the route would reject can't be typed in the first place
            type="select" if options else "text",
            options=options,
            default=meta["default"],
            example=examples.get(name),
            # each value is one path segment and must stay in its place
            quote="strict",
        )

    # ":uid" -> "{uid}", so the template can format the route itself. Only the
    # route is substituted: the base URL carries a port, which looks exactly
    # like a route parameter.
    route_path = _PARAMETER_PATTERN.sub(r"{\1}", f"/{namespace}{path}")
    url_template = f"{_base_url()}{route_path}"

    site = (namespace_info.get("url") or "").strip()
    name = (route.get("name") or "").strip() or path.strip("/") or namespace

    return SourceTemplate(
        name=name,
        bridge_short_name=f"{MARKER_PREFIX}{namespace}{path}",
        url=f"https://{site}" if site else "https://docs.rsshub.app",
        description=(
            route.get("description") or namespace_info.get("description") or name
        )[:2000],
        context=(namespace_info.get("name") or namespace).strip(),
        parameters=parameters,
        url_template=url_template,
    )


def _drop_imported_templates() -> None:
    with get_db_con() as cur:
        cur.execute(
            "DELETE FROM source_templates WHERE bridge_short_name LIKE %s",
            (f"{MARKER_PREFIX}%",),
        )


def rsshub_get_templates_job() -> None:
    if not is_configured():
        # RSSHub was removed from the deployment: take its routes out of the
        # catalog rather than leave templates that can no longer be fetched.
        try:
            _drop_imported_templates()
        except Exception as e:
            logging.error(f"Failed to drop RSSHub templates: {e}")
        return

    try:
        response = requests.get(
            f"{_base_url()}/api/namespace", timeout=CATALOG_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        namespaces = response.json()
    except requests.RequestException as e:
        logging.warning(f"Could not read the RSSHub route catalog: {e}")
        return
    except ValueError as e:
        # an instance that doesn't serve the catalog answers with HTML; the
        # generic "RSSHub Route" template still works, so this isn't fatal
        logging.warning(f"RSSHub route catalog was not JSON: {e}")
        return

    if not isinstance(namespaces, dict):
        logging.warning("RSSHub route catalog had an unexpected shape")
        return

    imported = 0
    for namespace, namespace_info in namespaces.items():
        if not isinstance(namespace_info, dict):
            continue
        for path, route in (namespace_info.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            try:
                template = route_to_template(namespace, namespace_info, path, route)
                if template is None:
                    continue
                template.create()
                imported += 1
            except Exception as e:
                logging.debug(f"Skipped RSSHub route {namespace}{path}: {e}")

    logging.info(f"Imported {imported} RSSHub route(s) as source templates")
