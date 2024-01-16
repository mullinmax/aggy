FROM postgres:latest

# Copy the custom scripts to the container
COPY migrate.sh /migrate.sh
COPY migrate.sql /migrate.sql
COPY custom-entrypoint.sh /custom-entrypoint.sh

# Make the scripts executable
RUN chmod +x /migrate.sh /custom-entrypoint.sh

# Set the custom script as the entrypoint
ENTRYPOINT ["/custom-entrypoint.sh"]
