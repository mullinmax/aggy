#!/bin/bash

# `up --abort-on-container-exit` tore the whole stack down as soon as *any*
# container exited -- and the flyway container exits, successfully, the moment
# the migrations are applied. That happened before pytest had produced a line
# of output, so every run ended with the stack stopped, no tests executed, and
# an exit status of 0. The green tick meant nothing.
#
# Instead: start everything detached (compose still honours depends_on, so the
# test container starts only once flyway has completed), then wait on the test
# container specifically and exit with pytest's own status.
set -u

compose_file="docker-compose.test.yml"

docker-compose -f $compose_file up --build -d || exit 1

container=$(docker-compose -f $compose_file ps -q test-aggy-api)
if [ -z "$container" ]; then
  echo "test container never started" >&2
  docker-compose -f $compose_file logs
  docker-compose -f $compose_file down
  exit 1
fi

status=$(docker wait "$container")
docker logs "$container"

docker-compose -f $compose_file down
exit "$status"
