#!/bin/bash
# build.sh

echo "Building blinder base image..."
docker build -t blinder-base:latest ./src/shared

echo "Building ingest and webui services..."
docker-compose up --build
