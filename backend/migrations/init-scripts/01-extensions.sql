-- Enable required PostgreSQL extensions
-- uuid-ossp: For UUID generation
-- pgcrypto: For cryptographic functions

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
