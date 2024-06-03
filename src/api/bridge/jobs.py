import logging
import requests
from bs4 import BeautifulSoup
import json

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
            bridge_uri = bridge.find("a", href=True)["href"]
            bridge_description = bridge.find("p", class_="description").text.strip()

            for form in bridge.find_all("form", class_="bridge-form"):
                context_input = form.find("input", {"name": "context"})
                if context_input is None:
                    logging.warning(
                        f"Context input not found in form for bridge: {bridge_name}"
                    )
                    continue

                context = context_input["value"]
                bridge_parameters = parse_parameters(form)

                bridge_template = FeedTemplate(
                    name=f"{bridge_name} ({context})",
                    uri=bridge_uri,
                    description=bridge_description,
                    context=context,
                    parameters=bridge_parameters,
                )

                bridge_template.save()
                bridge_list.append(bridge_template)

        # Convert to JSON serializable format
        bridge_list_serializable = [
            {
                "name": template.name,
                "uri": str(template.uri),  # Convert HttpUrl to string
                "description": template.description,
                "context": template.context,
                "parameters": {
                    param_name: param.dict()
                    for param_name, param in template.parameters.items()
                },
            }
            for template in bridge_list
        ]

        logging.info(
            f"RSS bridge templates: {json.dumps(bridge_list_serializable, indent=4)}"
        )

    except Exception as e:
        logging.error(f"Failed to get RSS bridge templates: {e}")
        return None
