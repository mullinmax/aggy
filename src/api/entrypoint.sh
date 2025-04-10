#!/bin/bash
# Initialize the Airflow database
airflow db init

# Start the webserver and scheduler in the background
airflow webserver & airflow scheduler &

# Wait for Airflow to be ready
sleep 30

# Run tests
pytest -x /src/api/tests/

# Keep the container running
wait
