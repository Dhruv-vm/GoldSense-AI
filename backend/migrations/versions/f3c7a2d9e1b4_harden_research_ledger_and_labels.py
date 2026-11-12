"""harden_research_ledger_and_labels

Closes Claude Audit #3 findings A3-1 .. A3-4:
  A3-1  A BACKTEST forecast_runs/research_feature_snapshots row could be UPDATEd into
        generation_mode='PROSPECTIVE', bypassing the INSERT-only hindsight trigger.
  A3-2  PROSPECTIVE forecast_evaluations rows could be UPDATEd / DELETEd.
  A3-3  TRUNCATE bypassed the row-level triggers.
  A3-4  news_labels rows (append-only by protocol) could be UPDATEd / DELETEd.
  A3-11 hindsight guard counted non-target rows (wrong unit / rate_type) as post-origin publications.

Revision ID: f3c7a2d9e1b4
Revises: e8b3c1d45207
Create Date: 2026-11-11 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f3c7a2d9e1b4"
down_revision: Union[str, Sequence[str], None] = "e8b3c1d45207"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PG_TRUNCATE_TABLES = ("forecast_runs", "forecast_evaluations", "research_feature_snapshots", "news_labels")


def _hindsight_pg_function(extra_filter: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION fn_guard_prospective_no_hindsight()
    RETURNS trigger AS $$
    DECLARE
        post_count integer;
    BEGIN
        IF NEW.generation_mode = 'PROSPECTIVE' THEN
            IF NEW.target_observation_id IS NOT NULL OR NEW.target_observed_at IS NOT NULL THEN
                RAISE EXCEPTION 'DB Hindsight Violation: prospective forecast cannot pre-populate target observation';
            END IF;
            IF NEW.generated_at < NEW.origin_observed_at THEN
                RAISE EXCEPTION 'DB Hindsight Violation: generated_at (%) precedes origin_observed_at (%)', NEW.generated_at, NEW.origin_observed_at;
            END IF;
            SELECT COUNT(*) INTO post_count
            FROM bullion_rate_observations
            WHERE product_id = 'MJDTA_GOLD_24K'
              AND city_code = 'CHENNAI'
              AND source_product_id = 'MJDTA_GOLD'
              AND validation_status = 'VALID'{extra_filter}
              AND observed_at > NEW.origin_observed_at;
            IF post_count >= NEW.horizon_publications THEN
                RAISE EXCEPTION 'DB Hindsight Violation: % post-origin MJDTA observation(s) already exist for h=%', post_count, NEW.horizon_publications;
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def _hindsight_sqlite_trigger(extra_filter: str) -> str:
    return f"""
    CREATE TRIGGER trg_forecast_runs_no_hindsight_sqlite
    BEFORE INSERT ON forecast_runs
    FOR EACH ROW WHEN NEW.generation_mode = 'PROSPECTIVE' AND (
        NEW.target_observation_id IS NOT NULL
        OR NEW.target_observed_at IS NOT NULL
        OR NEW.generated_at < NEW.origin_observed_at
        OR (
            SELECT COUNT(*)
            FROM bullion_rate_observations
            WHERE product_id = 'MJDTA_GOLD_24K'
              AND city_code = 'CHENNAI'
              AND source_product_id = 'MJDTA_GOLD'
              AND validation_status = 'VALID'{extra_filter}
              AND observed_at > NEW.origin_observed_at
        ) >= NEW.horizon_publications
    )
    BEGIN
        SELECT RAISE(ABORT, 'DB Hindsight Violation: invalid prospective forecast');
    END;
    """


# A3-11: the hindsight guard must count exactly the observations the MJDTA loader treats as
# the target series, otherwise non-series rows (10g quotes, RETAIL rows) block legitimate
# prospective forecasts.
_TARGET_SERIES_FILTER = """
              AND unit = '1g'
              AND rate_type = 'MJDTA_BENCHMARK'
              AND source_published_at IS NOT NULL"""


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        # A3-1: block any UPDATE/DELETE touching a PROSPECTIVE row, including an UPDATE that would
        # *turn* a row into PROSPECTIVE (NEW.generation_mode), on runs, snapshots and evaluations (A3-2).
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_block_prospective_ledger_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    IF OLD.generation_mode = 'PROSPECTIVE' THEN
                        RAISE EXCEPTION 'DB Immutability Violation: PROSPECTIVE % rows are append-only (DELETE prohibited)', TG_TABLE_NAME;
                    END IF;
                    RETURN OLD;
                END IF;
                IF OLD.generation_mode = 'PROSPECTIVE' OR NEW.generation_mode = 'PROSPECTIVE' THEN
                    RAISE EXCEPTION 'DB Immutability Violation: PROSPECTIVE % rows are append-only and cannot be created or changed by UPDATE', TG_TABLE_NAME;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_forecast_evaluations_immutable_pg
            BEFORE UPDATE OR DELETE ON forecast_evaluations
            FOR EACH ROW EXECUTE FUNCTION fn_block_prospective_ledger_mutation();
            """
        )
        # A3-4: news_labels are append-only for every row.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_block_append_only_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'DB Immutability Violation: % rows are append-only (% prohibited)', TG_TABLE_NAME, TG_OP;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_news_labels_append_only_pg
            BEFORE UPDATE OR DELETE ON news_labels
            FOR EACH ROW EXECUTE FUNCTION fn_block_append_only_mutation();
            """
        )
        # A3-3: statement-level TRUNCATE guard on every ledger table.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_block_ledger_truncate()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'DB Immutability Violation: TRUNCATE of % is prohibited', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table in _PG_TRUNCATE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_truncate_pg
                BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION fn_block_ledger_truncate();
                """
            )

    elif dialect == "sqlite":
        # SQLite has no TRUNCATE statement; mirror the row-level rules.
        for table in ("forecast_runs", "research_feature_snapshots"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_promote_sqlite
                BEFORE UPDATE ON {table}
                FOR EACH ROW WHEN NEW.generation_mode = 'PROSPECTIVE'
                BEGIN
                    SELECT RAISE(ABORT, 'DB Immutability Violation: rows cannot be promoted to PROSPECTIVE by UPDATE');
                END;
                """
            )
        op.execute(
            """
            CREATE TRIGGER trg_forecast_evaluations_no_update_sqlite
            BEFORE UPDATE ON forecast_evaluations
            FOR EACH ROW WHEN OLD.generation_mode = 'PROSPECTIVE' OR NEW.generation_mode = 'PROSPECTIVE'
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: PROSPECTIVE forecast_evaluations are append-only');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_forecast_evaluations_no_delete_sqlite
            BEFORE DELETE ON forecast_evaluations
            FOR EACH ROW WHEN OLD.generation_mode = 'PROSPECTIVE'
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: PROSPECTIVE forecast_evaluations cannot be deleted');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_news_labels_no_update_sqlite
            BEFORE UPDATE ON news_labels
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: news_labels are append-only');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_news_labels_no_delete_sqlite
            BEFORE DELETE ON news_labels
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: news_labels cannot be deleted');
            END;
            """
        )


    if dialect == "postgresql":
        op.execute(_hindsight_pg_function(_TARGET_SERIES_FILTER))
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_hindsight_sqlite;")
        op.execute(_hindsight_sqlite_trigger(_TARGET_SERIES_FILTER))

def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.execute(_hindsight_pg_function(""))
        for table in _PG_TRUNCATE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate_pg ON {table};")
        op.execute("DROP FUNCTION IF EXISTS fn_block_ledger_truncate();")
        op.execute("DROP TRIGGER IF EXISTS trg_news_labels_append_only_pg ON news_labels;")
        op.execute("DROP FUNCTION IF EXISTS fn_block_append_only_mutation();")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_evaluations_immutable_pg ON forecast_evaluations;")
        # Restore the e8b3c1d45207 version of the mutation guard (OLD-only check).
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_block_prospective_ledger_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF OLD.generation_mode = 'PROSPECTIVE' THEN
                    RAISE EXCEPTION 'DB Immutability Violation: PROSPECTIVE % rows are append-only (UPDATE/DELETE prohibited)', TG_TABLE_NAME;
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    elif dialect == "sqlite":
        for name in (
            "trg_forecast_runs_no_promote_sqlite",
            "trg_research_feature_snapshots_no_promote_sqlite",
            "trg_forecast_evaluations_no_update_sqlite",
            "trg_forecast_evaluations_no_delete_sqlite",
            "trg_news_labels_no_update_sqlite",
            "trg_news_labels_no_delete_sqlite",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name};")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_hindsight_sqlite;")
        op.execute(_hindsight_sqlite_trigger(""))
