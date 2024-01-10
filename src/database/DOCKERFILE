FROM postgres:latest

# Copy the initialization script to the container
COPY init.sql /docker-entrypoint-initdb.d/

# No need for CMD or ENTRYPOINT as we're using the base image's
