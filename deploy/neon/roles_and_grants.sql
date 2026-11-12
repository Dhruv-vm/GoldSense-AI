-- VMD Bullion — Neon PostgreSQL Role Separation & Least-Privilege Security Policy (A3-FINAL-2)
--
-- IMPORTANT:
--   1. Do NOT run this file automatically in CI runtime jobs; review and apply as DBA / Neon owner.
--   2. Set strong passwords separately in Neon Console / psql (never commit credentials in Git):
--        ALTER ROLE vmd_migrator WITH PASSWORD '<STRONG_MIGRATION_PASSWORD>';
--        ALTER ROLE vmd_app_runtime WITH PASSWORD '<STRONG_RUNTIME_PASSWORD>';
--        ALTER ROLE vmd_research_readonly WITH PASSWORD '<STRONG_READONLY_PASSWORD>';
--
-- Role Responsibilities:
--   - vmd_migrator:          Owns protected tables, sequences, views, triggers, and functions. Runs `alembic upgrade head`.
--   - vmd_app_runtime:       FastAPI API, Oracle KJPL worker, and GitHub collector jobs.
--                            Has ONLY SELECT, INSERT on protected append-only ledgers (no UPDATE/DELETE/TRUNCATE/DDL).
--   - vmd_research_readonly: Reporting / notebook / read-only dashboards (SELECT only).

-- 0. Prevent arbitrary object creation in public schema
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 1. Provision distinct non-superuser roles (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vmd_migrator') THEN
        CREATE ROLE vmd_migrator NOLOGIN;
    END IF;
    ALTER ROLE vmd_migrator WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vmd_app_runtime') THEN
        CREATE ROLE vmd_app_runtime NOLOGIN;
    END IF;
    ALTER ROLE vmd_app_runtime WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vmd_research_readonly') THEN
        CREATE ROLE vmd_research_readonly NOLOGIN;
    END IF;
    ALTER ROLE vmd_research_readonly WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
END
$$;

GRANT USAGE, CREATE ON SCHEMA public TO vmd_migrator;
GRANT USAGE ON SCHEMA public TO vmd_app_runtime;
GRANT USAGE ON SCHEMA public TO vmd_research_readonly;

-- 2. Transfer ownership of all tables, sequences, and trigger functions to vmd_migrator
DO $$
DECLARE
    obj RECORD;
BEGIN
    FOR obj IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO vmd_migrator', obj.tablename);
    END LOOP;

    FOR obj IN
        SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO vmd_migrator', obj.sequencename);
    END LOOP;

    FOR obj IN
        SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.prokind IN ('f', 'p')
    LOOP
        EXECUTE format('ALTER FUNCTION public.%I(%s) OWNER TO vmd_migrator', obj.proname, obj.args);
    END LOOP;
END
$$;

-- 3. Strip all default/broad grants before applying least-privilege permissions
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM PUBLIC, vmd_app_runtime, vmd_research_readonly;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, vmd_app_runtime, vmd_research_readonly;

-- 4. Protected Append-Only Research Ledgers & Raw Observations: SELECT + INSERT ONLY
GRANT SELECT, INSERT ON TABLE
    public.forecast_runs,
    public.research_feature_snapshots,
    public.forecast_evaluations,
    public.forecast_evaluation_reassessments,
    public.news_labels,
    public.news_collection_runs,
    public.collector_runs,
    public.bullion_rate_observations
TO vmd_app_runtime;

-- Explicitly ensure UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES are NEVER granted on protected ledgers
REVOKE UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES ON TABLE
    public.forecast_runs,
    public.research_feature_snapshots,
    public.forecast_evaluations,
    public.forecast_evaluation_reassessments,
    public.news_labels,
    public.news_collection_runs,
    public.collector_runs,
    public.bullion_rate_observations
FROM PUBLIC, vmd_app_runtime, vmd_research_readonly;

-- 5. Mutable Operational Catalog, Latest State, News & User Tables (still NO TRUNCATE / NO TRIGGER / NO DDL)
GRANT SELECT, INSERT, UPDATE ON TABLE
    public.bullion_cities,
    public.bullion_products,
    public.bullion_latest_rates,
    public.data_source_status,
    public.news_clusters,
    public.news_articles,
    public.gold_rates,
    public.market_rates,
    public.predictions,
    public.feature_snapshots
TO vmd_app_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.portfolio_holdings,
    public.alert_rules
TO vmd_app_runtime;

-- Runtime can read current Alembic revision for fail-closed health checks, never mutate it
GRANT SELECT ON TABLE public.alembic_version TO vmd_app_runtime, vmd_research_readonly;

-- Sequences needed for INSERT operations
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vmd_app_runtime;

-- 6. Read-Only Research / Reporting Role
GRANT SELECT ON ALL TABLES IN SCHEMA public TO vmd_research_readonly;

-- 7. Default privileges for future migrations run by vmd_migrator
ALTER DEFAULT PRIVILEGES FOR ROLE vmd_migrator IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC, vmd_app_runtime, vmd_research_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE vmd_migrator IN SCHEMA public
    GRANT SELECT ON TABLES TO vmd_research_readonly;
