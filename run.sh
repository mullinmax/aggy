#!/bin/bash

# Check if DEV_NAME is set
if [ -z "$DEV_NAME" ]; then
  echo "Error: DEV_NAME environment variable is not set."
  exit 1
fi

compose_file="docker-compose.yml"

echo "Stopping and removing containers for $DEV_NAME..."
docker-compose -f $compose_file down

echo "Building ingest and webui services for $DEV_NAME..."
docker-compose -f $compose_file up --build --remove-orphans

echo "Stopping and removing containers for $DEV_NAME..."
docker-compose -f $compose_file down
