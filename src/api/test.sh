#!/bin/bash

compose_file="docker-compose.test.yml"
docker-compose -f $compose_file up --build --abort-on-container-exit
docker-compose -f $compose_file down
