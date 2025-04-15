#!/bin/bash
# Initialize the Airflow database
airflow db init

# Start the webserver and scheduler in the background
airflow webserver & airflow scheduler &

# Wait for Airflow to be ready
sleep 10


airflow users  create --role Admin --username admin --email admin --firstname admin --lastname admin --password admin

# if env argument is test:
if [ "$1" = "test" ]; then
    # Run tests
    pytest -x /src/api/tests/
    exit 0
else
    python /src/api/main.py
fi

# Keep the container running
wait
