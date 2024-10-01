#!/bin/bash
compose_file="docker-compose.yml"

echo "Stopping and removing containers..."
docker-compose -f $compose_file down

echo "Building ingest and webui services..."
docker-compose -f $compose_file up --build --remove-orphans

echo "Stopping and removing containers..."
docker-compose -f $compose_file down
