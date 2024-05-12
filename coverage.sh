#!/bin/bash

compose_file="src/api/docker-compose.yml"
docker-compose -f $compose_file up --build -d
echo "Waiting for the database to be ready..."
export DB_HOST=dev-blinder-db
export DB_PORT=6379
export JWT_ALGORITHM=HS256
export JWT_SECRET=429bceb2ab20f5785a4b609a725b0164be73a95d8ce04706ed8366cfe6ade896

sleep 5

echo "Database is ready - running tests now"

pytest src/api/tests --cov=src/api --cov-report=xml:coverage.xml --cov-report=term-missing
docker-compose -f $compose_file down
