#!/usr/bin/env bash
# Create the database and its two roles in a CI PostgreSQL service.
#
# The same two-role split as the local cluster (ADR 0003): the application owns
# the schema, and the QA role holds SELECT and nothing else. CI is where that
# separation matters most - it is the environment nobody is watching.
#
# Expects PGHOST, PGPORT, PGUSER, PGPASSWORD for the superuser, plus
# APP_DB_USER / APP_DB_PASSWORD / DB_USER / DB_PASSWORD / DB_NAME.
set -euo pipefail

: "${DB_NAME:?DB_NAME is required}"
: "${APP_DB_USER:?APP_DB_USER is required}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"

echo "==> Creating roles"
psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_DB_USER}') THEN
        CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;
SQL

echo "==> Creating database ${DB_NAME}"
if [ "$(psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")" != "1" ]; then
    psql -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE ${DB_NAME} OWNER ${APP_DB_USER}"
fi

echo "==> Granting SELECT-only access to ${DB_USER}"
# ALTER DEFAULT PRIVILEGES is the part that is easy to miss: the application has
# not created its tables yet, so GRANT SELECT ON ALL TABLES grants nothing.
# Default privileges apply to tables the owning role creates later.
psql -v ON_ERROR_STOP=1 -q -d "${DB_NAME}" <<SQL
GRANT CONNECT ON DATABASE ${DB_NAME} TO ${DB_USER};
ALTER SCHEMA public OWNER TO ${APP_DB_USER};
GRANT USAGE ON SCHEMA public TO ${DB_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${APP_DB_USER} IN SCHEMA public
    GRANT SELECT ON TABLES TO ${DB_USER};
SQL

echo "Database ready: ${DB_NAME} (owner ${APP_DB_USER}, read-only ${DB_USER})"
