#!/bin/bash
# build.sh

docker compose down

echo "Building blinder shared image..."
docker build -t blinder-shared:latest ./src/shared

echo "Building ingest and webui services..."
docker-compose up --build
