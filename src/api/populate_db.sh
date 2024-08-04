# script to setup a test user for end to end testing of the API

name="tuser"
password="pass"
category="cat1"

#create user
curl -X 'POST' \
  'https://codehostapi.doze.dev/auth/signup' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "password": "user",
  "username": "pass"
}'

# get token
token=$(curl -X 'POST' \
  'https://codehostapi.doze.dev/auth/login' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "password": "user",
  "username": "pass"
}' | jq -r '.access_token')

# create a category
category_hash=$(curl -X 'POST' \
    'https://codehostapi.doze.dev/category/create?category_name=cat1' \
    -H 'accept: application/json' \
    -H "Authorization: Bearer $token" \
    -d '' | jq -r '.category_name_hash')

# list all feed templates:
feed_template=$(curl -X 'GET' \
  'https://codehostapi.doze.dev/feed_template/list_all' \
  -H 'accept: application/json' \
  -H "Authorization: Bearer $token" | jq -r 'to_entries | .[0]')

feed_template_hash=$(echo $feed_template | jq -r '.key')
feed_template_name=$(echo $feed_template | jq -r '.value')

echo "feed_template_hash: $feed_template_hash"
echo "feed_template_name: $feed_template_name"
