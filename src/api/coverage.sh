#!/bin/bash

compose_file="docker-compose.yml"
docker-compose -f $compose_file up --build -d

export DB_HOST=dev-aggy-db
export DB_PORT=6379
export JWT_ALGORITHM=HS256
export JWT_SECRET=429bceb2ab20f5785a4b609a725b0164be73a95d8ce04706ed8366cfe6ade896
export RSS_BRIDGE_HOST=dev-aggy-rss-bridge
export RSS_BRIDGE_PORT=80
export BUILD_VERSION=0.0.0-beta
export OLLAMA_EMBEDDING_MODEL=mxbai-embed-large:latest

pytest tests -x --ff --cov=. --cov-report=xml:coverage.xml --cov-report=term-missing
docker-compose -f $compose_file down
