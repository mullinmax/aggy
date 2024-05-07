#!/bin/bash
# build.sh
echo "Stopping and removing containers..."
docker-compose down

echo "Building ingest and webui services..."
docker-compose up --build --remove-orphans
