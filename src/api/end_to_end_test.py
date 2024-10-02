import requests

# curl_request() {
#   echo "Executing curl command: curl -sS -w '\n%{http_code}' $@"
#   local response=$(curl -sS -w '\n%{http_code}' "$@")
#   local http_code=$(echo "$response" | tail -n1)
#   local body=$(echo "$response" | sed '$ d')

#   echo "HTTP Response Code: $http_code"
#   echo "Response Body: $body"

#   if [[ "$http_code" -ne 200 ]]; then
#     echo "Error: Received HTTP code $http_code" >&2
#     echo "$body" >&2
#   fi

#   echo "$body"
#   return $http_code
# }


# signup user
# echo "Creating user..."
# # Create user
# response=$(curl_request -X 'POST' \
#   'https://codehostapi.doze.dev/auth/signup' \
#   -H 'accept: application/json' \
#   -H 'Content-Type: application/json' \
#   -d "{
#   \"username\": \"$name\",
#   \"password\": \"$password\"
# }")
# echo "Create user response: $response"


def create_user(name, password):
    requests.post(
        "https://codehostapi.doze.dev/auth/signup",
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json={"username": name, "password": password},
    )


# echo "Logging in to get token..."
# # Get token
# response=$(curl_request -X 'POST' \
#   'https://codehostapi.doze.dev/auth/login' \
#   -H 'accept: application/json' \
#   -H 'Content-Type: application/json' \
#   -d "{
#   \"username\": \"$name\",
#   \"password\": \"$password\"
# }")
# echo "Login response: $response"


def login(name, password) -> str:
    response = requests.post(
        "https://codehostapi.doze.dev/auth/login",
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json={"username": name, "password": password},
    )
    return response.json()["access_token"]


# echo "Creating feed..."
# # Create a feed
# response=$(curl_request -X 'POST' \
#   "https://codehostapi.doze.dev/feed/create?feed_name=$feed" \
#   -H 'accept: application/json' \
#   -H "Authorization: Bearer $token" \
#   -d '')
# echo "Create feed response: $response"


def create_feed(token, feed):
    response = requests.post(
        f"https://codehostapi.doze.dev/feed/create?feed_name={feed}",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    return response.json()["feed_name_hash"]


# echo "Listing all source templates..."
# # List all source templates
# response=$(curl_request -X 'GET' \
#   'https://codehostapi.doze.dev/source_template/list_all' \
#   -H 'accept: application/json' \
#   -H "Authorization: Bearer $token")
# echo "List all source templates response: $response"
def list_all_source_templates(token):
    response = requests.get(
        "https://codehostapi.doze.dev/source_template/list_all",
        headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    return response.json()


#   # Get template details
#   response=$(curl_request -X 'GET' \
#     "https://codehostapi.doze.dev/source_template/get?name_hash=$source_template_hash" \
#     -H 'accept: application/json' \
#     -H "Authorization: Bearer $token")
#   echo "Get template details response: $response"
def get_template_details(token, source_template_hash):
    response = requests.get(
        f"https://codehostapi.doze.dev/source_template/get?name_hash={source_template_hash}",
        headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    return response.json()


# get all sources already in a feed
# curl -X 'GET' \
#   'https://codehostapi.doze.dev/feed/sources?feed_name_hash=123123' \
def get_existing_sources(token, feed_hash):
    response = requests.get(
        f"https://codehostapi.doze.dev/feed/sources?feed_name_hash={feed_hash}",
        headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    return [source["source_name_hash"] for source in response.json()]


# create a source from a template
# curl -X 'POST' \
#   'https://codehostapi.doze.dev/source_template/create' \
#   -H 'accept: application/json' \
#   -H 'Content-Type: application/json' \
#   -d '{
#   "feed_hash": "feed_hash_456",
#   "source_name": "Example Source Name",
#   "source_template_name_hash": "example_hash_123",
#   "parameters": {
#     "parameter_name": "value"
#   }
# }'
def create_source(token, feed_hash, source_name, source_template_hash):
    response = requests.post(
        "https://codehostapi.doze.dev/source_template/create",
        headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
        json={
            "feed_hash": feed_hash,
            "source_name": source_name,
            "source_template_name_hash": source_template_hash,
            "parameters": {},
        },
    )
    return response.json()


def main():
    create_user("user", "pass")
    token = login("user", "pass")
    feed_hash = create_feed(token, "feed")
    source_templates = list_all_source_templates(token)
    existing_sources = get_existing_sources(token, feed_hash)

    print("Existing sources:", existing_sources)

    # filter down to sources we haven't already used
    new_sources = {
        source_template_hash: source_template_name
        for source_template_hash, source_template_name in source_templates.items()
        if source_template_hash not in existing_sources
    }

    for source_template_hash, source_template_name in new_sources.items():
        template = get_template_details(token, source_template_hash)

        required = [
            p for p in template["parameters"] if template["parameters"][p]["required"]
        ]
        num_required = len(required)
        if num_required == 0:
            break
    else:
        print("No suitable source template found.")
        return

    print("Feed hash:", feed_hash)
    print("Selected source_template_hash:", source_template_hash)
    source_name_hash = create_source(
        token, feed_hash, source_template_name, source_template_hash
    )
    print("Source name hash:", source_name_hash)


if __name__ == "__main__":
    main()
