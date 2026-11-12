"""enforce_prospective_immutability_and_model_version

Revision ID: e8b3c1d45207
Revises: d91e4a7b2019
Create Date: 2026-11-11 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e8b3c1d45207"
down_revision: Union[str, Sequence[str], None] = "d91e4a7b2019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    with op.batch_alter_table("forecast_runs") as batch_op:
        batch_op.drop_index("idx_forecast_mode_arm_horizon_origin")
        batch_op.drop_constraint("uq_forecast_run_mode_origin_arm_horizon", type_="unique")
        batch_op.create_unique_constraint(
            "uq_forecast_run_mode_model_origin_arm_horizon",
            [
                "protocol_version",
                "generation_mode",
                "model_version",
                "arm",
                "horizon_publications",
                "origin_observed_at",
            ],
        )
        batch_op.create_index(
            "idx_forecast_mode_arm_horizon_origin",
            ["generation_mode", "model_version", "arm", "horizon_publications", "origin_observed_at"],
            unique=False,
        )

    if dialect == "postgresql":
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

            CREATE TRIGGER trg_forecast_runs_immutable_pg
            BEFORE UPDATE OR DELETE ON forecast_runs
            FOR EACH ROW EXECUTE FUNCTION fn_block_prospective_ledger_mutation();

            CREATE TRIGGER trg_snapshots_immutable_pg
            BEFORE UPDATE OR DELETE ON research_feature_snapshots
            FOR EACH ROW EXECUTE FUNCTION fn_block_prospective_ledger_mutation();

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
                      AND validation_status = 'VALID'
                      AND observed_at > NEW.origin_observed_at;
                    IF post_count >= NEW.horizon_publications THEN
                        RAISE EXCEPTION 'DB Hindsight Violation: % post-origin MJDTA observation(s) already exist for h=%', post_count, NEW.horizon_publications;
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_forecast_runs_no_hindsight_pg
            BEFORE INSERT ON forecast_runs
            FOR EACH ROW EXECUTE FUNCTION fn_guard_prospective_no_hindsight();
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_forecast_runs_no_update_sqlite
            BEFORE UPDATE ON forecast_runs
            FOR EACH ROW WHEN OLD.generation_mode = 'PROSPECTIVE'
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: PROSPECTIVE forecast_runs are append-only');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_forecast_runs_no_delete_sqlite
            BEFORE DELETE ON forecast_runs
            FOR EACH ROW WHEN OLD.generation_mode = 'PROSPECTIVE'
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: PROSPECTIVE forecast_runs cannot be deleted');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_snapshots_no_update_sqlite
            BEFORE UPDATE ON research_feature_snapshots
            FOR EACH ROW WHEN OLD.generation_mode = 'PROSPECTIVE'
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: PROSPECTIVE snapshots are append-only');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_snapshots_no_delete_sqlite
            BEFORE DELETE ON research_feature_snapshots
            FOR EACH ROW WHEN OLD.generation_mode = 'PROSPECTIVE'
            BEGIN
                SELECT RAISE(ABORT, 'DB Immutability Violation: PROSPECTIVE snapshots cannot be deleted');
            END;
            """
        )
        op.execute(
            """
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
                      AND validation_status = 'VALID'
                      AND observed_at > NEW.origin_observed_at
                ) >= NEW.horizon_publications
            )
            BEGIN
                SELECT RAISE(ABORT, 'DB Hindsight Violation: invalid prospective forecast');
            END;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_hindsight_pg ON forecast_runs;")
        op.execute("DROP FUNCTION IF EXISTS fn_guard_prospective_no_hindsight();")
        op.execute("DROP TRIGGER IF EXISTS trg_snapshots_immutable_pg ON research_feature_snapshots;")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_immutable_pg ON forecast_runs;")
        op.execute("DROP FUNCTION IF EXISTS fn_block_prospective_ledger_mutation();")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_hindsight_sqlite;")
        op.execute("DROP TRIGGER IF EXISTS trg_snapshots_no_delete_sqlite;")
        op.execute("DROP TRIGGER IF EXISTS trg_snapshots_no_update_sqlite;")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_delete_sqlite;")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_update_sqlite;")

    with op.batch_alter_table("forecast_runs") as batch_op:
        batch_op.drop_index("idx_forecast_mode_arm_horizon_origin")
        batch_op.drop_constraint("uq_forecast_run_mode_model_origin_arm_horizon", type_="unique")
        batch_op.create_unique_constraint(
            "uq_forecast_run_mode_origin_arm_horizon",
            ["protocol_version", "generation_mode", "arm", "horizon_publications", "origin_observed_at"],
        )
        batch_op.create_index(
            "idx_forecast_mode_arm_horizon_origin",
            ["generation_mode", "arm", "horizon_publications", "origin_observed_at"],
            unique=False,
        )
