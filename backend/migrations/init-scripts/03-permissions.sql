-- Grant proper permissions to application user
-- Principle of least privilege: only what's needed

-- Connect to the application database
\c ritter_nroetschen

-- Grant schema usage
GRANT USAGE ON SCHEMA public TO ritter_app;

-- Grant table permissions
GRANT CREATE ON SCHEMA public TO ritter_app;

-- Allow ritter_app to access future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ritter_app;

-- Allow sequence usage for auto-incrementing IDs
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ritter_app;

-- Grant execute on functions
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO ritter_app;
