-- Grant proper permissions to application user
-- Principle of least privilege: only what's needed

-- Connect to the application database
\c TradingAssistantDB

-- Grant schema usage
GRANT USAGE ON SCHEMA public TO bamendjou_app;

-- Grant table permissions
GRANT CREATE ON SCHEMA public TO bamendjou_app;

-- Allow bamendjou_app to access future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bamendjou_app;

-- Allow sequence usage for auto-incrementing IDs
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO bamendjou_app;

-- Grant execute on functions
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO bamendjou_app;

-- ALTER DEFAULT PRIVILEGES above only covers objects created AFTER this script
-- runs. On a genuine fresh install that's every table (Alembic/SQLAlchemy
-- create them later), so this is normally sufficient. But if this script ever
-- runs against a database that was restored/seeded before bamendjou_app
-- existed (e.g. a pg_restore onto an existing volume), the tables that
-- already exist need an explicit grant too — default privileges do not apply
-- retroactively.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO bamendjou_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bamendjou_app;
