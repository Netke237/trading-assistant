#!/usr/bin/env bash
# Create dedicated application user
# This user has limited privileges compared to the postgres superuser
#
# Must be a .sh file, not .sql: the Postgres docker-entrypoint only expands
# environment variables (like $POSTGRES_PASSWORD) for *.sh scripts, which it
# sources directly. *.sql files are piped to psql verbatim with no shell
# substitution, so a literal '${POSTGRES_PASSWORD}' in a .sql file would have
# set the role's password to that literal string instead of the real value.
#
# The password is passed in via a psql variable (-v pw=...), NOT spliced
# directly into SQL text as a bash value — a raw splice breaks (and silently
# truncates the CREATE USER statement) if the password contains a single
# quote. psql's own quoted-literal substitution (:'pw') would normally handle
# that safely, but it does NOT work inside a dollar-quoted ($$ ... $$) block —
# psql skips variable interpolation there entirely, so a naive
# `CREATE USER ... WITH PASSWORD :'pw';` written inside `DO $$ ... $$;` sends
# the literal text ":'pw'" to the server and fails with a syntax error.
# Instead, build the whole DO-block command as a string via format('%L', ...)
# at the top level (outside any $$ block, where :'pw' interpolation does
# work), capture it into a variable with \gset, then execute that variable.

set -e

psql -v ON_ERROR_STOP=1 -v pw="$POSTGRES_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
	SELECT format(
	    'DO $do$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = ''bamendjou_app'') THEN CREATE USER bamendjou_app WITH PASSWORD %L; END IF; END $do$;',
	    :'pw'
	) AS create_user_cmd \gset

	:create_user_cmd

	-- Set connection limit to prevent resource exhaustion
	ALTER USER bamendjou_app WITH CONNECTION LIMIT 100;
EOSQL
