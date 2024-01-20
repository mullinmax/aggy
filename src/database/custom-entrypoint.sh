#!/bin/bash
set -e

# Wait for PostgreSQL to start
echo "Waiting for postgres to start..."
until pg_isready -h ${DB_HOST:-localhost} -U ${POSTGRES_USER:-postgres}; do
  sleep 1
done

echo "Postgres started, executing migration script..."
./migrate.sh

# Call the original entrypoint script
exec docker-entrypoint.sh postgres
