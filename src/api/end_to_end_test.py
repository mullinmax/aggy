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


# echo "Creating category..."
# # Create a category
# response=$(curl_request -X 'POST' \
#   "https://codehostapi.doze.dev/category/create?category_name=$category" \
#   -H 'accept: application/json' \
#   -H "Authorization: Bearer $token" \
#   -d '')
# echo "Create category response: $response"


def create_category(token, category):
    response = requests.post(
        f"https://codehostapi.doze.dev/category/create?category_name={category}",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    return response.json()["category_name_hash"]


# echo "Listing all feed templates..."
# # List all feed templates
# response=$(curl_request -X 'GET' \
#   'https://codehostapi.doze.dev/feed_template/list_all' \
#   -H 'accept: application/json' \
#   -H "Authorization: Bearer $token")
# echo "List all feed templates response: $response"
def list_all_feed_templates(token):
    response = requests.get(
        "https://codehostapi.doze.dev/feed_template/list_all",
        headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    return response.json()


#   # Get template details
#   response=$(curl_request -X 'GET' \
#     "https://codehostapi.doze.dev/feed_template/get?name_hash=$feed_template_hash" \
#     -H 'accept: application/json' \
#     -H "Authorization: Bearer $token")
#   echo "Get template details response: $response"
def get_template_details(token, feed_template_hash):
    response = requests.get(
        f"https://codehostapi.doze.dev/feed_template/get?name_hash={feed_template_hash}",
        headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    return response.json()


# create a feed from a template
# curl -X 'POST' \
#   'https://codehostapi.doze.dev/feed_template/create' \
#   -H 'accept: application/json' \
#   -H 'Content-Type: application/json' \
#   -d '{
#   "category_hash": "category_hash_456",
#   "feed_name": "Example Feed Name",
#   "feed_template_name_hash": "example_hash_123",
#   "parameters": {
#     "parameter_name": "value"
#   }
# }'
def create_feed(token, category_hash, feed_name, feed_template_hash):
    response = requests.post(
        "https://codehostapi.doze.dev/feed_template/create",
        headers={"accept": "application/json", "Authorization": f"Bearer {token}"},
        json={
            "category_hash": category_hash,
            "feed_name": feed_name,
            "feed_template_name_hash": feed_template_hash,
            "parameters": {},
        },
    )
    return response.json()


def main():
    create_user("user", "pass")
    token = login("user", "pass")
    category_hash = create_category(token, "category")
    feed_templates = list_all_feed_templates(token)
    for feed_template_hash, feed_template_name in feed_templates.items():
        template = get_template_details(token, feed_template_hash)
        if (
            len(
                [
                    p
                    for p in template["parameters"]
                    if template["parameters"][p]["required"]
                ]
            )
            == 0
        ):
            break
    else:
        print("No suitable feed template found.")
        return

    print("Category hash:", category_hash)
    print("Selected feed_template_hash:", feed_template_hash)
    feed_name_hash = create_feed(token, category_hash, "feed", feed_template_hash)
    print("Feed name hash:", feed_name_hash)


if __name__ == "__main__":
    main()
