#!/bin/bash

# Define an array of Docker Compose files
compose_files=("src/api/docker-compose.test.yml")

# Array to store exit codes
exit_codes=()

# Start each compose file in the background
for file in "${compose_files[@]}"; do
    echo "Starting tests with $file"
    docker-compose -f $file up --build --abort-on-container-exit
    # Capture the exit code immediately after docker-compose finishes
    exit_codes+=($?)
    docker-compose -f $file down
done

# Initialize an overall exit status
overall_exit_status=0

# Check exit codes from all containers
for exit_code in "${exit_codes[@]}"; do
    if [ "$exit_code" -ne 0 ]; then
        echo "A test failed with exit code $exit_code"
        overall_exit_status=1
    fi
done

# Final decision based on the aggregated exit statuses
if [ "$overall_exit_status" -ne 0 ]; then
    echo "Some tests failed."
    exit 1
else
    echo "All tests passed successfully."
    exit 0
fi
