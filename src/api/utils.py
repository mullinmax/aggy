from ollama import Client
from httpx import BasicAuth

from config import config


def get_ollama_connection() -> Client:
    ollama_args = {"host": config.get("OLLAMA_HOST") + ":" + config.get("OLLAMA_PORT")}

    auth_user = config.get("OLLAMA_USER", False)
    auth_password = config.get("OLLAMA_PASSWORD", False)
    if auth_user and auth_password:
        ollama_args["auth"] = BasicAuth(username=auth_user, password=auth_password)

    ollama = Client(**ollama_args)

    return ollama
