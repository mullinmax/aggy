-- Create schema_version table if it doesn't exist
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Function to check the current version
CREATE OR REPLACE FUNCTION get_current_version() RETURNS INTEGER AS $$
DECLARE
    v_version INTEGER;
BEGIN
    SELECT INTO v_version MAX(version) FROM schema_version;
    IF FOUND THEN
        RETURN v_version;
    ELSE
        RETURN 0; -- Default version if table is empty
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Initial schema setup (version 1)
DO $$
BEGIN
    IF get_current_version() < 1 THEN
        -- Migration 1: Create a new table
        CREATE TABLE IF NOT EXISTS user_data (
            id SERIAL PRIMARY KEY,
            name TEXT,
            description TEXT
        );
        
        -- Update schema version
        INSERT INTO schema_version (version) VALUES (1);
    END IF;
END;
$$;


CREATE TABLE IF NOT EXISTS user_data (
    id SERIAL PRIMARY KEY,
    name TEXT,
    description TEXT
);

-- Apply second migration (version 2)
DO $$
BEGIN
    IF get_current_version() < 2 THEN
        -- Migration 2: Populate user_data table with dummy data
        INSERT INTO user_data (name, description) VALUES
        ('Alice', 'Description for Alice'),
        ('Bob', 'Description for Bob'),
        ('Charlie', 'Description for Charlie');

        -- Update schema version
        INSERT INTO schema_version (version) VALUES (2);
    END IF;
END;
$$;

-- Repeat similar blocks for subsequent migrations
