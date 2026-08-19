-- Two roles, one privilege boundary. Runs once, on an empty data directory,
-- from the postgres image's docker-entrypoint-initdb.d hook.
--
-- The same split as scripts/local_db.ps1 and scripts/setup_ci_db.sh: the
-- application OWNS the schema, the QA role may only SELECT. A test can observe
-- any state the application produced and cannot manufacture state it never
-- would. See docs/adr/0003-read-only-db-role.md
--
-- Passwords come from the environment via the entrypoint's variable
-- substitution... which postgres does NOT do for .sql files. So this file is
-- deliberately written for the compose defaults and the values are local,
-- disposable, and documented rather than pretend-secret. A real deployment
-- creates roles with a provisioning tool, not with an init script.

CREATE ROLE claimdesk_app LOGIN PASSWORD 'compose-local-app';
CREATE ROLE claimdesk_qa_ro LOGIN PASSWORD 'compose-local-qa-ro';

-- POSTGRES_DB created the database already; take ownership of its schema so the
-- application can create its tables.
ALTER DATABASE claimdesk OWNER TO claimdesk_app;
ALTER SCHEMA public OWNER TO claimdesk_app;

GRANT CONNECT ON DATABASE claimdesk TO claimdesk_qa_ro;
GRANT USAGE ON SCHEMA public TO claimdesk_qa_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO claimdesk_qa_ro;

-- The line that is easy to miss and breaks everything downstream. At this point
-- the application has created no tables, so the GRANT above grants nothing.
-- DEFAULT PRIVILEGES apply to tables claimdesk_app creates LATER - which is all
-- of them.
ALTER DEFAULT PRIVILEGES FOR ROLE claimdesk_app IN SCHEMA public
    GRANT SELECT ON TABLES TO claimdesk_qa_ro;
