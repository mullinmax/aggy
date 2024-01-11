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
-- DO $$
-- BEGIN
--     IF get_current_version() < 1 THEN
--         -- Migration 1: Create a new table
--         CREATE TABLE IF NOT EXISTS your_new_table (
--             id SERIAL PRIMARY KEY,
--             name VARCHAR(255)
--         );
        
--         -- Update schema version
--         INSERT INTO schema_version (version) VALUES (1);
--     END IF;
-- END;
-- $$;

-- Apply second migration (version 2)
-- DO $$
-- BEGIN
--     IF get_current_version() < 2 THEN
--         -- Migration 2: Alter column type and add new column
--         ALTER TABLE your_new_table
--         ALTER COLUMN name TYPE TEXT,
--         ADD COLUMN description TEXT;

--         -- Update schema version
--         INSERT INTO schema_version (version) VALUES (2);
--     END IF;
-- END;
-- $$;

-- Repeat similar blocks for subsequent migrations
