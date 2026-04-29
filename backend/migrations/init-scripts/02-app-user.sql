-- Create dedicated application user
-- This user has limited privileges compared to the postgres superuser

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ritter_app') THEN
        CREATE USER ritter_app WITH PASSWORD '${POSTGRES_PASSWORD}';
    END IF;
END
$$;

-- Set connection limit to prevent resource exhaustion
ALTER USER ritter_app WITH CONNECTION LIMIT 100;
