import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import config
from db.base import get_db_con
from db.source_template import SourceTemplate, SourceTemplateParameter

# Bridges hidden from the template catalog because Aggy ships a better
# built-in alternative (see builtin_templates.py). RedditBridge scrapes
# reddit's JSON API anonymously and gets rate limited from most self-hosted
# IPs; the native reddit RSS templates work where it doesn't.
HIDDEN_BRIDGES = ("RedditBridge",)


def parse_parameters(form):
    parameters = {}
    for param_group in form.find_all("div", class_="parameters"):
        for label in param_group.find_all("label"):
            param_info = {
                "name": label.text.strip(),
                "required": False,
                "type": "text",
                "default": "",
                "example": "",
                "title": "",
            }

            input_element = label.find_next_sibling(["input", "select"])

            if input_element:
                param_name = input_element.get("name", "")
                if input_element.name == "input":
                    param_info.update(
                        {
                            "type": input_element.get("type", "text"),
                            "required": input_element.has_attr("required"),
                            "default": input_element.get("value", ""),
                            "example": input_element.get("placeholder", ""),
                        }
                    )
                elif input_element.name == "select":
                    param_info.update(
                        {
                            "type": "select",
                            "options": {
                                option["value"]: option.text
                                for option in input_element.find_all("option")
                            },
                            "default": input_element.find("option", selected=True)[
                                "value"
                            ]
                            if input_element.find("option", selected=True)
                            else None,
                        }
                    )

                info_element = input_element.find_next_sibling("i")
                if info_element:
                    param_info["title"] = (
                        info_element.get("title", "")
                        .split("Example (right click to use):")[0]
                        .strip()
                    )

                parameters[param_name] = SourceTemplateParameter(**param_info)
    return parameters


def rss_bridge_get_templates_job() -> None:
    if config.get("RSS_BRIDGE_HOST") is None:
        logging.info("RSS_BRIDGE_HOST is not set in the config")
        return

    # Drop hidden-bridge templates left over from earlier catalog imports.
    # Existing sources keep working; only the template disappears from search.
    try:
        with get_db_con() as cur:
            cur.execute(
                "DELETE FROM source_templates WHERE bridge_short_name IN %s",
                (HIDDEN_BRIDGES,),
            )
            if cur.rowcount:
                logging.info(f"Removed {cur.rowcount} hidden bridge template(s)")
    except Exception as e:
        logging.error(f"Failed to remove hidden bridge templates: {e}")

    try:
        url = f"http://{config.get('RSS_BRIDGE_HOST')}:{config.get('RSS_BRIDGE_PORT')}/"
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        soup = BeautifulSoup(response.content, "html.parser")
        bridge_list = []
        failures = 0

        # Find all bridge elements. Each bridge is parsed independently so
        # one malformed bridge card can't abort the rest of the catalog.
        for bridge in soup.find_all("section", class_="bridge-card"):
            try:
                bridge_name = bridge.find("h2").text.strip()
                links = bridge.find("h2").find_all("a", href=True)
                bridge_url = next(
                    (a["href"] for a in links if not a["href"].startswith("#")), None
                )
                # bridges without a site link get the rss-bridge URL itself;
                # relative links are resolved against it
                bridge_url = urljoin(url, bridge_url) if bridge_url else url
                description_el = bridge.find("p", class_="description")
                bridge_description = (
                    description_el.text.strip() if description_el else bridge_name
                )
                bridge_short_name = bridge["data-short-name"]

                if bridge_short_name in HIDDEN_BRIDGES:
                    continue

                for form in bridge.find_all("form", class_="bridge-form"):
                    context = None

                    context_input = form.find("input", {"name": "context"})
                    if context_input is not None:
                        context = context_input.get("value")

                    bridge_template = SourceTemplate(
                        name=bridge_name,
                        bridge_short_name=bridge_short_name,
                        url=bridge_url,
                        description=bridge_description,
                        context=context,
                        parameters=parse_parameters(form),
                    )

                    bridge_template.create()
                    bridge_list.append(bridge_template)
            except Exception as e:
                failures += 1
                logging.warning(f"Failed to parse rss-bridge card: {e}")

        for bridge in bridge_list:
            logging.info(f"rss-bridge template created: {bridge.user_friendly_name}")

        logging.info(
            f"Total rss-bridge templates created: {len(bridge_list)} "
            f"({failures} bridge cards failed to parse)"
        )

    except Exception as e:
        logging.error(f"Failed to get RSS bridge templates: {e}")
        return None
