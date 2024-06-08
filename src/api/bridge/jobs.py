import logging
import requests
from bs4 import BeautifulSoup

from config import config
from db.feed_template import FeedTemplate, FeedTemplateParameter


def parse_parameters(form):
    parameters = {}
    for param_group in form.find_all("div", class_="parameters"):
        for label in param_group.find_all("label"):
            param_info = {
                "name": label.text.strip(),
                "required": False,
                "type": "text",
                "default": "",
                "placeholder": "",
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
                            "placeholder": input_element.get("placeholder", ""),
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

                parameters[param_name] = FeedTemplateParameter(**param_info)
    return parameters


def rss_bridge_get_templates_job() -> None:
    if config.get("RSS_BRIDGE_HOST") is None:
        logging.info("RSS_BRIDGE_HOST is not set in the config")
        return

    try:
        url = f"http://{config.get('RSS_BRIDGE_HOST')}:{config.get('RSS_BRIDGE_PORT')}/"
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        soup = BeautifulSoup(response.content, "html.parser")
        bridge_list = []

        # Find all bridge elements
        for bridge in soup.find_all("section", class_="bridge-card"):
            bridge_name = bridge.find("h2").text.strip()
            bridge_url = bridge.find("a", href=True)["href"]
            bridge_description = bridge.find("p", class_="description").text.strip()
            bridge_short_name = bridge["data-short-name"]

            for form in bridge.find_all("form", class_="bridge-form"):
                context = None

                context_input = form.find("input", {"name": "context"})
                if context_input is not None:
                    context = context_input.get("value")

                bridge_template = FeedTemplate(
                    name=bridge_name,
                    bridge_short_name=bridge_short_name,
                    url=bridge_url,
                    description=bridge_description,
                    context=context,
                    parameters=parse_parameters(form),
                )

                bridge_template.create()
                bridge_list.append(bridge_template)

        for bridge in bridge_list:
            logging.info(f"rss-ridge template created: {bridge.user_friendly_name}")

        logging.info(f"Total rss-bridge templates created: {len(bridge_list)}")

    except Exception as e:
        logging.error(f"Failed to get RSS bridge templates: {e}")
        return None
