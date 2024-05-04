#!/bin/bash

# Start up all services in detached mode
docker-compose -f docker-compose.test.yml up --build -d

# Define the service name of your test container
test_service_name="test-blinder-shared"

# Wait for the test container to complete
echo "Waiting for the test service to complete..."
docker-compose -f docker-compose.test.yml wait $test_service_name

# Retrieve the container ID directly from Docker, not through docker-compose
container_id=$(docker ps -aqf "name=${test_service_name}")

# Make sure we actually have a container ID
if [ -z "$container_id" ]; then
    echo "Failed to get container ID."
    docker-compose -f docker-compose.test.yml down
    exit 1
fi

# Capture the exit code of the test service
exit_code=$(docker inspect -f '{{ .State.ExitCode }}' $container_id)

# Output logs from the test container
echo "Test service exited with code $exit_code"
echo "Outputting logs from the test container:"
docker-compose -f docker-compose.test.yml logs $test_service_name

# Stop and remove containers, networks, etc.
docker-compose -f docker-compose.test.yml down

# Exit with the captured exit code
exit $exit_code
