from urllib.parse import urlencode


def build_query_string(params: dict) -> str:
    """Builds a URL-encoded query string from a dictionary of parameters."""
    # Remove any key-value pairs where the value is None
    filtered_params = {key: value for key, value in params.items() if value is not None}
    return urlencode(filtered_params)


def build_api_request_args(
    path: str, params: dict = None, data: dict = None, token: str = None
):
    """Builds the arguments for an API request."""
    args = {"url": path}
    if params is not None:
        args["url"] += f"?{build_query_string(params)}"
    if data is not None:
        args["json"] = data
    if token is not None:
        args["headers"] = {"Authorization": f"Bearer {token}"}
    return args
