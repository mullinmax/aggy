#!/bin/bash

compose_file="docker-compose.yml"
docker-compose -f $compose_file up --build -d

export DB_HOST=dev-blinder-db
export DB_PORT=6379
export JWT_ALGORITHM=HS256
export JWT_SECRET=429bceb2ab20f5785a4b609a725b0164be73a95d8ce04706ed8366cfe6ade896

pytest tests --cov=. --cov-report=xml:coverage.xml --cov-report=term-missing
docker-compose -f $compose_file down
