"""a3_final_ledger_security_corrections

Closes Audit #3 Final Verification findings:
  - A3-FINAL-1A: DB-level validation of forecast_evaluations BEFORE INSERT.
  - A3-FINAL-1B: DB-level temporal provenance & availability enforcement on news_labels & news_collection_runs.
  - A3-FINAL-3:  MJDTA correction lineage (observation_kind, revision_number, supersedes_observation_id),
                 prospective publication-level deduplication, and append-only forecast_evaluation_reassessments.
  - A3-FINAL-4:  Raw clock text & inferred precision columns on bullion_rate_observations.
  - A3-FINAL-5:  DB-enforced partial unique constraint for concurrent non-deterministic (Ollama) label writes.
  - A3-FINAL-6:  Persist protocol_sha256 on forecast_runs & research_feature_snapshots (nullable for legacy rows).

Revision ID: 9b4e1d8c3a02
Revises: f3c7a2d9e1b4
Create Date: 2026-11-12 11:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b4e1d8c3a02"
down_revision: Union[str, Sequence[str], None] = "f3c7a2d9e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EXTRA_APPEND_ONLY_TABLES = (
    "forecast_evaluation_reassessments",
    "bullion_rate_observations",
    "news_collection_runs",
)

_TARGET_SERIES_FILTER = """
              AND unit = '1g'
              AND rate_type = 'MJDTA_BENCHMARK'
              AND source_published_at IS NOT NULL
              AND observation_kind = 'ORIGINAL'"""


def _hindsight_pg_function_v2() -> str:
    return f"""
    CREATE OR REPLACE FUNCTION fn_guard_prospective_no_hindsight()
    RETURNS trigger AS $$
    DECLARE
        post_count integer;
        origin_pub timestamptz;
    BEGIN
        IF NEW.generation_mode = 'PROSPECTIVE' THEN
            IF NEW.target_observation_id IS NOT NULL OR NEW.target_observed_at IS NOT NULL THEN
                RAISE EXCEPTION 'DB Hindsight Violation: prospective forecast cannot pre-populate target observation';
            END IF;
            IF NEW.generated_at < NEW.origin_observed_at THEN
                RAISE EXCEPTION 'DB Hindsight Violation: generated_at (%) precedes origin_observed_at (%)', NEW.generated_at, NEW.origin_observed_at;
            END IF;
            IF NEW.origin_observation_id IS NOT NULL THEN
                SELECT source_published_at INTO origin_pub
                FROM bullion_rate_observations
                WHERE id = NEW.origin_observation_id;
            END IF;
            origin_pub := COALESCE(origin_pub, NEW.origin_source_published_at, NEW.origin_observed_at);

            SELECT COUNT(DISTINCT o.source_published_at) INTO post_count
            FROM bullion_rate_observations o
            JOIN bullion_products p ON p.product_id = o.product_id
            WHERE o.product_id = 'MJDTA_GOLD_24K'
              AND o.city_code = 'CHENNAI'
              AND o.source_product_id = 'MJDTA_GOLD'
              AND o.validation_status = 'VALID'
              AND o.unit = '1g'
              AND o.rate_type = 'MJDTA_BENCHMARK'
              AND o.source_published_at IS NOT NULL
              AND o.observation_kind = 'ORIGINAL'
              AND COALESCE(o.normalized_price_per_gram, o.price) > 0
              AND p.purity = 0.9990
              AND p.unit = '1g'
              AND p.rate_type = 'MJDTA_BENCHMARK'
              AND o.observed_at > NEW.origin_observed_at
              AND o.source_published_at > origin_pub;
            IF post_count >= NEW.horizon_publications THEN
                RAISE EXCEPTION 'DB Hindsight Violation: % post-origin MJDTA observation(s) already exist for h=%', post_count, NEW.horizon_publications;
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def _hindsight_sqlite_trigger_v2() -> str:
    return f"""
    CREATE TRIGGER trg_forecast_runs_no_hindsight_sqlite
    BEFORE INSERT ON forecast_runs
    FOR EACH ROW WHEN NEW.generation_mode = 'PROSPECTIVE' AND (
        NEW.target_observation_id IS NOT NULL
        OR NEW.target_observed_at IS NOT NULL
        OR julianday(NEW.generated_at) < julianday(NEW.origin_observed_at)
        OR (
            SELECT COUNT(DISTINCT o.source_published_at)
            FROM bullion_rate_observations o
            JOIN bullion_products p ON p.product_id = o.product_id
            WHERE o.product_id = 'MJDTA_GOLD_24K'
              AND o.city_code = 'CHENNAI'
              AND o.source_product_id = 'MJDTA_GOLD'
              AND o.validation_status = 'VALID'
              AND o.unit = '1g'
              AND o.rate_type = 'MJDTA_BENCHMARK'
              AND o.source_published_at IS NOT NULL
              AND o.observation_kind = 'ORIGINAL'
              AND COALESCE(o.normalized_price_per_gram, o.price) > 0
              AND p.purity = 0.9990
              AND p.unit = '1g'
              AND p.rate_type = 'MJDTA_BENCHMARK'
              AND julianday(o.observed_at) > julianday(NEW.origin_observed_at)
              AND julianday(o.source_published_at) > julianday(
                  COALESCE(
                      (SELECT source_published_at FROM bullion_rate_observations WHERE id = NEW.origin_observation_id),
                      NEW.origin_source_published_at,
                      NEW.origin_observed_at
                  )
              )
        ) >= NEW.horizon_publications
    )
    BEGIN
        SELECT RAISE(ABORT, 'DB Hindsight Violation: invalid prospective forecast');
    END;
    """


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    # 1. bullion_rate_observations: correction lineage + clock-only raw metadata
    op.add_column("bullion_rate_observations", sa.Column("raw_source_published_time", sa.String(length=64), nullable=True))
    op.add_column("bullion_rate_observations", sa.Column("source_timestamp_precision", sa.String(length=24), nullable=True))
    op.add_column(
        "bullion_rate_observations",
        sa.Column("is_timestamp_inferred", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "bullion_rate_observations",
        sa.Column("observation_kind", sa.String(length=24), server_default="ORIGINAL", nullable=False),
    )
    op.add_column(
        "bullion_rate_observations",
        sa.Column("revision_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("bullion_rate_observations", sa.Column("supersedes_observation_id", sa.Integer(), nullable=True))
    op.add_column("bullion_rate_observations", sa.Column("correction_reason", sa.Text(), nullable=True))
    if dialect != "sqlite":
        op.create_foreign_key(
            "fk_bullion_obs_supersedes",
            "bullion_rate_observations",
            "bullion_rate_observations",
            ["supersedes_observation_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_bullion_mjdta_pub_revision
        ON bullion_rate_observations (city_code, product_id, source_product_id, source_published_at, revision_number)
        WHERE validation_status = 'VALID' AND rate_type = 'MJDTA_BENCHMARK' AND source_published_at IS NOT NULL
        """
    )

    # 2. research_feature_snapshots & forecast_runs: origin_source_published_at + protocol_sha256 (left NULL for historical rows)
    op.add_column("research_feature_snapshots", sa.Column("origin_source_published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("research_feature_snapshots", sa.Column("protocol_sha256", sa.String(length=64), nullable=True))
    op.create_index("ix_research_feature_snapshots_origin_source_published_at", "research_feature_snapshots", ["origin_source_published_at"])

    op.add_column("forecast_runs", sa.Column("protocol_sha256", sa.String(length=64), nullable=True))
    op.add_column("forecast_runs", sa.Column("origin_source_published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_forecast_runs_origin_source_published_at", "forecast_runs", ["origin_source_published_at"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_prospective_origin_publication
        ON forecast_runs (protocol_version, generation_mode, model_version, arm, horizon_publications, origin_source_published_at)
        WHERE generation_mode = 'PROSPECTIVE' AND origin_source_published_at IS NOT NULL
        """
    )

    # 3. forecast_evaluations: protocol_version + model_version
    op.add_column("forecast_evaluations", sa.Column("protocol_version", sa.String(length=32), nullable=True))
    op.add_column("forecast_evaluations", sa.Column("model_version", sa.String(length=64), nullable=True))

    # 4. forecast_evaluation_reassessments table (A3-FINAL-3)
    op.create_table(
        "forecast_evaluation_reassessments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reassessment_id", sa.String(length=64), nullable=False),
        sa.Column("forecast_id", sa.String(length=64), nullable=False),
        sa.Column("original_target_observation_id", sa.Integer(), nullable=True),
        sa.Column("corrected_target_observation_id", sa.Integer(), nullable=False),
        sa.Column("corrected_revision_number", sa.Integer(), nullable=False),
        sa.Column("matured_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrected_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrected_actual_price_inr_per_g", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("corrected_actual_log_return", sa.Float(), nullable=False),
        sa.Column("corrected_actual_direction", sa.String(length=16), nullable=False),
        sa.Column("abs_error_log_return", sa.Float(), nullable=True),
        sa.Column("sq_error_log_return", sa.Float(), nullable=True),
        sa.Column("abs_error_inr_per_g", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("direction_correct", sa.Boolean(), nullable=True),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("reassessed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["forecast_id"], ["forecast_evaluations.forecast_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["corrected_target_observation_id"], ["bullion_rate_observations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("forecast_id", "corrected_target_observation_id", name="uq_eval_reassessment_forecast_target"),
    )
    op.create_index("ix_forecast_evaluation_reassessments_reassessment_id", "forecast_evaluation_reassessments", ["reassessment_id"], unique=True)
    op.create_index("ix_forecast_evaluation_reassessments_forecast_id", "forecast_evaluation_reassessments", ["forecast_id"])
    op.create_index("ix_eval_reassess_corr_target_id", "forecast_evaluation_reassessments", ["corrected_target_observation_id"])

    # 5. news_collection_runs & news_labels provenance + LLM concurrent unique index (A3-FINAL-1B, A3-FINAL-5)
    op.add_column("news_collection_runs", sa.Column("db_recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("news_collection_runs", sa.Column("db_tx_id", sa.String(length=64), nullable=True))

    op.add_column("news_labels", sa.Column("collection_run_id", sa.String(length=64), nullable=True))
    op.add_column("news_labels", sa.Column("classification_scope", sa.String(length=24), server_default="CLUSTER", nullable=False))
    op.add_column("news_labels", sa.Column("classifier_impl_version", sa.String(length=64), nullable=True))
    op.add_column("news_labels", sa.Column("classification_identity_hash", sa.String(length=64), nullable=True))
    op.add_column("news_labels", sa.Column("db_recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("news_labels", sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_news_labels_collection_run_id", "news_labels", ["collection_run_id"])
    op.create_index("ix_news_labels_available_at", "news_labels", ["available_at"])

    if dialect != "sqlite":
        op.create_foreign_key(
            "fk_news_labels_story_cluster",
            "news_labels",
            "news_clusters",
            ["story_cluster_id"],
            ["story_cluster_id"],
            ondelete="RESTRICT",
        )
        op.create_foreign_key(
            "fk_news_labels_collection_run",
            "news_labels",
            "news_collection_runs",
            ["collection_run_id"],
            ["run_id"],
            ondelete="RESTRICT",
        )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_news_label_llm_identity
        ON news_labels (classification_identity_hash)
        WHERE model_name <> 'deterministic_rules_v2' AND classification_identity_hash IS NOT NULL
        """
    )

    # 6. Database validation & immutability triggers
    if dialect == "postgresql":
        op.execute(_hindsight_pg_function_v2())

        # A3-FINAL-1A: Validate PROSPECTIVE forecast_evaluations BEFORE INSERT
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_validate_prospective_evaluation_insert()
            RETURNS trigger AS $$
            DECLARE
                fc RECORD;
                tgt RECORD;
                origin_pub timestamptz;
                post_pub_count integer;
                expected_price numeric(14,2);
                expected_lr double precision;
                expected_dir text;
            BEGIN
                SELECT * INTO fc FROM forecast_runs WHERE forecast_id = NEW.forecast_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'DB Evaluation Violation: forecast_id % does not exist', NEW.forecast_id;
                END IF;

                IF NEW.generation_mode = 'PROSPECTIVE' OR fc.generation_mode = 'PROSPECTIVE' THEN
                    IF fc.generation_mode <> 'PROSPECTIVE' OR NEW.generation_mode <> 'PROSPECTIVE' THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: mode mismatch (forecast=%, evaluation=%)', fc.generation_mode, NEW.generation_mode;
                    END IF;
                    IF NEW.arm <> fc.arm OR NEW.horizon_publications <> fc.horizon_publications OR NEW.origin_observed_at <> fc.origin_observed_at THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: evaluation provenance (arm/horizon/origin) does not match forecast %', NEW.forecast_id;
                    END IF;
                    IF NEW.model_version IS NOT NULL AND NEW.model_version <> fc.model_version THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: model_version mismatch (% <> %)', NEW.model_version, fc.model_version;
                    END IF;
                    IF NEW.protocol_version IS NOT NULL AND NEW.protocol_version <> fc.protocol_version THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: protocol_version mismatch (% <> %)', NEW.protocol_version, fc.protocol_version;
                    END IF;
                    IF NEW.target_observation_id IS NULL THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: target_observation_id is required for PROSPECTIVE evaluation';
                    END IF;

                    SELECT o.*, p.purity AS prod_purity, p.unit AS prod_unit, p.rate_type AS prod_rate_type
                    INTO tgt
                    FROM bullion_rate_observations o
                    JOIN bullion_products p ON p.product_id = o.product_id
                    WHERE o.id = NEW.target_observation_id;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: target_observation_id % not found', NEW.target_observation_id;
                    END IF;

                    IF tgt.product_id <> 'MJDTA_GOLD_24K'
                       OR tgt.city_code <> 'CHENNAI'
                       OR tgt.source_product_id <> 'MJDTA_GOLD'
                       OR tgt.validation_status <> 'VALID'
                       OR tgt.unit <> '1g'
                       OR tgt.rate_type <> 'MJDTA_BENCHMARK'
                       OR tgt.source_published_at IS NULL
                       OR tgt.observation_kind <> 'ORIGINAL'
                       OR tgt.prod_purity <> 0.9990
                       OR tgt.prod_unit <> '1g'
                       OR tgt.prod_rate_type <> 'MJDTA_BENCHMARK' THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: target_observation_id % is not an authoritative MJDTA observation', NEW.target_observation_id;
                    END IF;

                    IF tgt.observed_at <= fc.origin_observed_at THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: target observation (%) must be strictly after origin (%)', tgt.observed_at, fc.origin_observed_at;
                    END IF;
                    IF tgt.observed_at <= fc.generated_at THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: target observation (%) predates forecast generation (%)', tgt.observed_at, fc.generated_at;
                    END IF;
                    IF NEW.matured_observed_at <> tgt.observed_at THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: fabricated matured_observed_at (% <> %)', NEW.matured_observed_at, tgt.observed_at;
                    END IF;
                    IF NEW.evaluated_at < tgt.observed_at OR NEW.evaluated_at < fc.generated_at THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: evaluated_at (%) precedes target maturity or forecast generation', NEW.evaluated_at;
                    END IF;

                    IF fc.origin_observation_id IS NOT NULL THEN
                        SELECT source_published_at INTO origin_pub FROM bullion_rate_observations WHERE id = fc.origin_observation_id;
                    END IF;
                    origin_pub := COALESCE(origin_pub, fc.origin_source_published_at, fc.origin_observed_at);

                    SELECT COUNT(DISTINCT source_published_at) INTO post_pub_count
                    FROM bullion_rate_observations
                    WHERE product_id = 'MJDTA_GOLD_24K'
                      AND city_code = 'CHENNAI'
                      AND source_product_id = 'MJDTA_GOLD'
                      AND validation_status = 'VALID'
                      AND unit = '1g'
                      AND rate_type = 'MJDTA_BENCHMARK'
                      AND source_published_at IS NOT NULL
                      AND observation_kind = 'ORIGINAL'
                      AND observed_at > fc.origin_observed_at
                      AND source_published_at > origin_pub
                      AND source_published_at <= tgt.source_published_at;
                    IF post_pub_count <> fc.horizon_publications THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: target publication rank % does not satisfy horizon %', post_pub_count, fc.horizon_publications;
                    END IF;

                    expected_price := COALESCE(tgt.normalized_price_per_gram, tgt.price);
                    IF ABS(NEW.actual_price_inr_per_g - expected_price) > 0.01 THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: actual_price (% <> %) does not match target observation', NEW.actual_price_inr_per_g, expected_price;
                    END IF;

                    expected_lr := LN((expected_price / fc.origin_price_inr_per_g)::double precision);
                    IF ABS(NEW.actual_log_return - expected_lr) > 0.0001 THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: actual_log_return (% <> %) does not match target return', NEW.actual_log_return, expected_lr;
                    END IF;

                    IF ABS(expected_lr) <= 0.0005 THEN
                        expected_dir := 'FLAT';
                    ELSIF expected_lr > 0 THEN
                        expected_dir := 'UP';
                    ELSE
                        expected_dir := 'DOWN';
                    END IF;
                    IF NEW.actual_direction <> expected_dir THEN
                        RAISE EXCEPTION 'DB Evaluation Violation: actual_direction (% <> %)', NEW.actual_direction, expected_dir;
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_forecast_evaluations_validate_insert_pg
            BEFORE INSERT ON forecast_evaluations
            FOR EACH ROW EXECUTE FUNCTION fn_validate_prospective_evaluation_insert();
            """
        )

        # A3-FINAL-3: Validate forecast_evaluation_reassessments BEFORE INSERT
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_validate_eval_reassessment_insert()
            RETURNS trigger AS $$
            DECLARE
                ev RECORD;
                orig_tgt RECORD;
                corr_tgt RECORD;
            BEGIN
                SELECT * INTO ev FROM forecast_evaluations WHERE forecast_id = NEW.forecast_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'DB Reassessment Violation: missing forecast_evaluation %', NEW.forecast_id;
                END IF;
                SELECT * INTO corr_tgt FROM bullion_rate_observations WHERE id = NEW.corrected_target_observation_id;
                IF NOT FOUND OR corr_tgt.observation_kind <> 'CORRECTION' OR corr_tgt.validation_status <> 'VALID' THEN
                    RAISE EXCEPTION 'DB Reassessment Violation: corrected_target_observation_id % must be a VALID CORRECTION', NEW.corrected_target_observation_id;
                END IF;
                IF ev.target_observation_id IS NOT NULL THEN
                    SELECT * INTO orig_tgt FROM bullion_rate_observations WHERE id = ev.target_observation_id;
                    IF orig_tgt.source_published_at IS DISTINCT FROM corr_tgt.source_published_at THEN
                        RAISE EXCEPTION 'DB Reassessment Violation: corrected observation does not share original source_published_at';
                    END IF;
                END IF;
                NEW.reassessed_at := clock_timestamp();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_forecast_evaluation_reassessments_validate_insert_pg
            BEFORE INSERT ON forecast_evaluation_reassessments
            FOR EACH ROW EXECUTE FUNCTION fn_validate_eval_reassessment_insert();
            """
        )

        # A3-FINAL-1B: news_collection_runs server-controlled db_recorded_at & db_tx_id
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_guard_news_collection_run_insert()
            RETURNS trigger AS $$
            BEGIN
                NEW.db_recorded_at := clock_timestamp();
                NEW.db_tx_id := pg_current_xact_id()::text;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_news_collection_runs_guard_insert_pg
            BEFORE INSERT ON news_collection_runs
            FOR EACH ROW EXECUTE FUNCTION fn_guard_news_collection_run_insert();
            """
        )

        # A3-FINAL-1B: news_labels temporal provenance & trusted availability
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_validate_news_label_insert()
            RETURNS trigger AS $$
            DECLARE
                clu RECORD;
                art RECORD;
                nrun RECORD;
                min_avail timestamptz;
            BEGIN
                NEW.db_recorded_at := clock_timestamp();

                SELECT * INTO clu FROM news_clusters WHERE story_cluster_id = NEW.story_cluster_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'DB Provenance Violation: missing news_cluster %', NEW.story_cluster_id;
                END IF;
                IF clu.first_seen_at IS NOT NULL AND NEW.label_created_at < clu.first_seen_at THEN
                    RAISE EXCEPTION 'DB Temporal Leakage: label_created_at (%) precedes cluster first_seen_at (%)', NEW.label_created_at, clu.first_seen_at;
                END IF;

                IF NEW.article_id IS NOT NULL THEN
                    SELECT * INTO art FROM news_articles WHERE id = NEW.article_id;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'DB Provenance Violation: missing article_id %', NEW.article_id;
                    END IF;
                    IF art.story_cluster_id IS NULL OR art.story_cluster_id <> NEW.story_cluster_id THEN
                        RAISE EXCEPTION 'DB Provenance Violation: article % does not belong to cluster %', NEW.article_id, NEW.story_cluster_id;
                    END IF;
                    IF art.first_seen_at IS NULL THEN
                        RAISE EXCEPTION 'DB Temporal Leakage: article % has NULL first_seen_at', NEW.article_id;
                    END IF;
                    IF NEW.label_created_at < art.first_seen_at OR NEW.label_created_at < art.published_at THEN
                        RAISE EXCEPTION 'DB Temporal Leakage: label_created_at (%) precedes article availability', NEW.label_created_at;
                    END IF;
                END IF;

                IF NEW.collection_run_id IS NOT NULL THEN
                    SELECT * INTO nrun FROM news_collection_runs WHERE run_id = NEW.collection_run_id;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'DB Provenance Violation: missing collection_run_id %', NEW.collection_run_id;
                    END IF;
                    IF nrun.db_tx_id IS NOT NULL AND nrun.db_tx_id <> pg_current_xact_id()::text THEN
                        RAISE EXCEPTION 'DB Provenance Violation: cannot attach label to closed collection_run_id %', NEW.collection_run_id;
                    END IF;
                    IF NEW.label_created_at < nrun.started_at THEN
                        RAISE EXCEPTION 'DB Temporal Leakage: label_created_at (%) precedes run started_at (%)', NEW.label_created_at, nrun.started_at;
                    END IF;
                    min_avail := GREATEST(NEW.label_created_at, nrun.completed_at);
                    IF clu.first_seen_at IS NOT NULL THEN
                        min_avail := GREATEST(min_avail, clu.first_seen_at);
                    END IF;
                    IF NEW.article_id IS NOT NULL AND art.first_seen_at IS NOT NULL THEN
                        min_avail := GREATEST(min_avail, art.first_seen_at);
                    END IF;
                    NEW.available_at := min_avail;
                ELSE
                    -- Without an active open collection run, DB controls availability strictly at NOW()
                    NEW.available_at := NEW.db_recorded_at;
                END IF;

                IF NEW.model_name <> 'deterministic_rules_v2' AND NEW.classification_identity_hash IS NULL THEN
                    NEW.classification_identity_hash := md5(
                        COALESCE(NEW.story_cluster_id, '') || '|' ||
                        COALESCE(NEW.classification_scope, 'CLUSTER') || '|' ||
                        (CASE WHEN COALESCE(NEW.classification_scope, 'CLUSTER') = 'ARTICLE' THEN COALESCE(NEW.article_id::text, '') ELSE '' END) || '|' ||
                        COALESCE(NEW.model_name, '') || '|' ||
                        COALESCE(NEW.sentiment_version, '') || '|' ||
                        COALESCE(NEW.model_digest, '') || '|' ||
                        COALESCE(NEW.prompt_version, '') || '|' ||
                        COALESCE(NEW.classifier_impl_version, '')
                    );
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_news_labels_validate_insert_pg
            BEFORE INSERT ON news_labels
            FOR EACH ROW EXECUTE FUNCTION fn_validate_news_label_insert();
            """
        )

        # Append-only immutability & TRUNCATE guards on new / protected ledger tables
        for tbl in _EXTRA_APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{tbl}_append_only_pg
                BEFORE UPDATE OR DELETE ON {tbl}
                FOR EACH ROW EXECUTE FUNCTION fn_block_append_only_mutation();

                CREATE TRIGGER trg_{tbl}_no_truncate_pg
                BEFORE TRUNCATE ON {tbl}
                FOR EACH STATEMENT EXECUTE FUNCTION fn_block_ledger_truncate();
                """
            )

    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_hindsight_sqlite;")
        op.execute(_hindsight_sqlite_trigger_v2())

        op.execute(
            """
            CREATE TRIGGER trg_forecast_evaluations_validate_insert_sqlite
            BEFORE INSERT ON forecast_evaluations
            FOR EACH ROW WHEN NEW.generation_mode = 'PROSPECTIVE' OR (
                SELECT generation_mode FROM forecast_runs WHERE forecast_id = NEW.forecast_id
            ) = 'PROSPECTIVE'
            BEGIN
                SELECT CASE
                    WHEN NOT EXISTS (SELECT 1 FROM forecast_runs WHERE forecast_id = NEW.forecast_id)
                        THEN RAISE(ABORT, 'DB Evaluation Violation: missing forecast_id')
                    WHEN NEW.generation_mode <> 'PROSPECTIVE'
                         OR (SELECT generation_mode FROM forecast_runs WHERE forecast_id = NEW.forecast_id) <> 'PROSPECTIVE'
                        THEN RAISE(ABORT, 'DB Evaluation Violation: mode mismatch')
                    WHEN NEW.arm <> (SELECT arm FROM forecast_runs WHERE forecast_id = NEW.forecast_id)
                         OR NEW.horizon_publications <> (SELECT horizon_publications FROM forecast_runs WHERE forecast_id = NEW.forecast_id)
                         OR ABS(julianday(NEW.origin_observed_at) - julianday((SELECT origin_observed_at FROM forecast_runs WHERE forecast_id = NEW.forecast_id))) > 1e-6
                        THEN RAISE(ABORT, 'DB Evaluation Violation: provenance mismatch')
                    WHEN (NEW.model_version IS NOT NULL AND NEW.model_version <> (SELECT model_version FROM forecast_runs WHERE forecast_id = NEW.forecast_id))
                         OR (NEW.protocol_version IS NOT NULL AND NEW.protocol_version <> (SELECT protocol_version FROM forecast_runs WHERE forecast_id = NEW.forecast_id))
                        THEN RAISE(ABORT, 'DB Evaluation Violation: model/protocol version mismatch')
                    WHEN NEW.target_observation_id IS NULL
                         OR NOT EXISTS (
                             SELECT 1 FROM bullion_rate_observations o
                             JOIN bullion_products p ON p.product_id = o.product_id
                             WHERE o.id = NEW.target_observation_id
                               AND o.product_id = 'MJDTA_GOLD_24K'
                               AND o.city_code = 'CHENNAI'
                               AND o.source_product_id = 'MJDTA_GOLD'
                               AND o.validation_status = 'VALID'
                               AND o.unit = '1g'
                               AND o.rate_type = 'MJDTA_BENCHMARK'
                               AND o.source_published_at IS NOT NULL
                               AND o.observation_kind = 'ORIGINAL'
                               AND p.purity = 0.9990
                               AND p.unit = '1g'
                               AND p.rate_type = 'MJDTA_BENCHMARK'
                         )
                        THEN RAISE(ABORT, 'DB Evaluation Violation: invalid target_observation_id')
                    WHEN julianday((SELECT observed_at FROM bullion_rate_observations WHERE id = NEW.target_observation_id)) <= julianday((SELECT origin_observed_at FROM forecast_runs WHERE forecast_id = NEW.forecast_id))
                         OR julianday((SELECT observed_at FROM bullion_rate_observations WHERE id = NEW.target_observation_id)) <= julianday((SELECT generated_at FROM forecast_runs WHERE forecast_id = NEW.forecast_id))
                        THEN RAISE(ABORT, 'DB Evaluation Violation: target does not postdate origin and generation')
                    WHEN ABS(julianday(NEW.matured_observed_at) - julianday((SELECT observed_at FROM bullion_rate_observations WHERE id = NEW.target_observation_id))) > 1e-6
                        THEN RAISE(ABORT, 'DB Evaluation Violation: matured_observed_at mismatch')
                    WHEN julianday(NEW.evaluated_at) < julianday((SELECT observed_at FROM bullion_rate_observations WHERE id = NEW.target_observation_id)) - 1e-6
                        THEN RAISE(ABORT, 'DB Evaluation Violation: evaluated_at precedes target maturity')
                    WHEN (
                        SELECT COUNT(DISTINCT source_published_at)
                        FROM bullion_rate_observations
                        WHERE product_id = 'MJDTA_GOLD_24K'
                          AND city_code = 'CHENNAI'
                          AND source_product_id = 'MJDTA_GOLD'
                          AND validation_status = 'VALID'
                          AND unit = '1g'
                          AND rate_type = 'MJDTA_BENCHMARK'
                          AND source_published_at IS NOT NULL
                          AND observation_kind = 'ORIGINAL'
                          AND julianday(observed_at) > julianday((SELECT origin_observed_at FROM forecast_runs WHERE forecast_id = NEW.forecast_id))
                          AND julianday(source_published_at) > julianday(
                              COALESCE(
                                  (SELECT source_published_at FROM bullion_rate_observations WHERE id = (SELECT origin_observation_id FROM forecast_runs WHERE forecast_id = NEW.forecast_id)),
                                  (SELECT origin_source_published_at FROM forecast_runs WHERE forecast_id = NEW.forecast_id),
                                  (SELECT origin_observed_at FROM forecast_runs WHERE forecast_id = NEW.forecast_id)
                              )
                          )
                          AND julianday(source_published_at) <= julianday((SELECT source_published_at FROM bullion_rate_observations WHERE id = NEW.target_observation_id))
                    ) <> (SELECT horizon_publications FROM forecast_runs WHERE forecast_id = NEW.forecast_id)
                        THEN RAISE(ABORT, 'DB Evaluation Violation: horizon publication count mismatch')
                    WHEN ABS(NEW.actual_price_inr_per_g - COALESCE((SELECT normalized_price_per_gram FROM bullion_rate_observations WHERE id = NEW.target_observation_id), (SELECT price FROM bullion_rate_observations WHERE id = NEW.target_observation_id))) > 0.01
                        THEN RAISE(ABORT, 'DB Evaluation Violation: actual_price mismatch')
                    WHEN ABS(NEW.actual_log_return - ln((1.0 * COALESCE((SELECT normalized_price_per_gram FROM bullion_rate_observations WHERE id = NEW.target_observation_id), (SELECT price FROM bullion_rate_observations WHERE id = NEW.target_observation_id))) / (1.0 * (SELECT origin_price_inr_per_g FROM forecast_runs WHERE forecast_id = NEW.forecast_id)))) > 0.0001
                        THEN RAISE(ABORT, 'DB Evaluation Violation: actual_log_return mismatch')
                END;
            END;
            """
        )

        op.execute(
            """
            CREATE TRIGGER trg_news_labels_validate_insert_sqlite
            BEFORE INSERT ON news_labels
            BEGIN
                SELECT CASE
                    WHEN NOT EXISTS (SELECT 1 FROM news_clusters WHERE story_cluster_id = NEW.story_cluster_id)
                        THEN RAISE(ABORT, 'DB Provenance Violation: missing news_cluster')
                    WHEN (SELECT first_seen_at FROM news_clusters WHERE story_cluster_id = NEW.story_cluster_id) IS NOT NULL
                         AND julianday(NEW.label_created_at) < julianday((SELECT first_seen_at FROM news_clusters WHERE story_cluster_id = NEW.story_cluster_id)) - 1e-6
                        THEN RAISE(ABORT, 'DB Temporal Leakage: label_created_at precedes cluster first_seen_at')
                    WHEN NEW.article_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM news_articles WHERE id = NEW.article_id)
                        THEN RAISE(ABORT, 'DB Provenance Violation: missing article_id')
                    WHEN NEW.article_id IS NOT NULL AND (
                        (SELECT story_cluster_id FROM news_articles WHERE id = NEW.article_id) IS NULL
                        OR (SELECT story_cluster_id FROM news_articles WHERE id = NEW.article_id) <> NEW.story_cluster_id
                    )
                        THEN RAISE(ABORT, 'DB Provenance Violation: article does not belong to cluster')
                    WHEN NEW.article_id IS NOT NULL AND (SELECT first_seen_at FROM news_articles WHERE id = NEW.article_id) IS NULL
                        THEN RAISE(ABORT, 'DB Temporal Leakage: article has NULL first_seen_at')
                    WHEN NEW.article_id IS NOT NULL AND (
                        julianday(NEW.label_created_at) < julianday((SELECT first_seen_at FROM news_articles WHERE id = NEW.article_id)) - 1e-6
                        OR julianday(NEW.label_created_at) < julianday((SELECT published_at FROM news_articles WHERE id = NEW.article_id)) - 1e-6
                    )
                        THEN RAISE(ABORT, 'DB Temporal Leakage: label_created_at precedes article availability')
                    WHEN NEW.collection_run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM news_collection_runs WHERE run_id = NEW.collection_run_id)
                        THEN RAISE(ABORT, 'DB Provenance Violation: missing collection_run_id')
                    WHEN NEW.collection_run_id IS NOT NULL AND julianday(NEW.label_created_at) < julianday((SELECT started_at FROM news_collection_runs WHERE run_id = NEW.collection_run_id)) - 1e-6
                        THEN RAISE(ABORT, 'DB Temporal Leakage: label_created_at precedes run started_at')
                    WHEN NEW.collection_run_id IS NULL AND julianday(NEW.available_at) < julianday('now') - (10.0 / 86400.0)
                        THEN RAISE(ABORT, 'DB Temporal Leakage: unlinked label cannot forge past available_at')
                    WHEN julianday(NEW.db_recorded_at) < julianday('now') - (10.0 / 86400.0)
                        THEN RAISE(ABORT, 'DB Temporal Leakage: cannot backdate db_recorded_at')
                END;
            END;
            """
        )

        for tbl in _EXTRA_APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{tbl}_no_update_sqlite
                BEFORE UPDATE ON {tbl}
                BEGIN
                    SELECT RAISE(ABORT, 'DB Immutability Violation: {tbl} rows are append-only');
                END;
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{tbl}_no_delete_sqlite
                BEFORE DELETE ON {tbl}
                BEGIN
                    SELECT RAISE(ABORT, 'DB Immutability Violation: {tbl} rows cannot be deleted');
                END;
                """
            )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        for tbl in _EXTRA_APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_no_truncate_pg ON {tbl};")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_append_only_pg ON {tbl};")
        op.execute("DROP TRIGGER IF EXISTS trg_news_labels_validate_insert_pg ON news_labels;")
        op.execute("DROP FUNCTION IF EXISTS fn_validate_news_label_insert();")
        op.execute("DROP TRIGGER IF EXISTS trg_news_collection_runs_guard_insert_pg ON news_collection_runs;")
        op.execute("DROP FUNCTION IF EXISTS fn_guard_news_collection_run_insert();")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_evaluation_reassessments_validate_insert_pg ON forecast_evaluation_reassessments;")
        op.execute("DROP FUNCTION IF EXISTS fn_validate_eval_reassessment_insert();")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_evaluations_validate_insert_pg ON forecast_evaluations;")
        op.execute("DROP FUNCTION IF EXISTS fn_validate_prospective_evaluation_insert();")
        # Restore f3c7a2d9e1b4 version of hindsight function
        op.execute(
            """
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
                      AND unit = '1g'
                      AND rate_type = 'MJDTA_BENCHMARK'
                      AND source_published_at IS NOT NULL
                      AND observed_at > NEW.origin_observed_at;
                    IF post_count >= NEW.horizon_publications THEN
                        RAISE EXCEPTION 'DB Hindsight Violation: % post-origin MJDTA observation(s) already exist for h=%', post_count, NEW.horizon_publications;
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    elif dialect == "sqlite":
        for tbl in _EXTRA_APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_no_update_sqlite;")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_no_delete_sqlite;")
        op.execute("DROP TRIGGER IF EXISTS trg_news_labels_validate_insert_sqlite;")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_evaluations_validate_insert_sqlite;")
        op.execute("DROP TRIGGER IF EXISTS trg_forecast_runs_no_hindsight_sqlite;")
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
                      AND unit = '1g'
                      AND rate_type = 'MJDTA_BENCHMARK'
                      AND source_published_at IS NOT NULL
                      AND observed_at > NEW.origin_observed_at
                ) >= NEW.horizon_publications
            )
            BEGIN
                SELECT RAISE(ABORT, 'DB Hindsight Violation: invalid prospective forecast');
            END;
            """
        )

    op.execute("DROP INDEX IF EXISTS uq_news_label_llm_identity;")
    if dialect != "sqlite":
        op.drop_constraint("fk_news_labels_collection_run", "news_labels", type_="foreignkey")
        op.drop_constraint("fk_news_labels_story_cluster", "news_labels", type_="foreignkey")
    op.drop_index("ix_news_labels_available_at", table_name="news_labels")
    op.drop_index("ix_news_labels_collection_run_id", table_name="news_labels")
    op.drop_column("news_labels", "available_at")
    op.drop_column("news_labels", "db_recorded_at")
    op.drop_column("news_labels", "classification_identity_hash")
    op.drop_column("news_labels", "classifier_impl_version")
    op.drop_column("news_labels", "classification_scope")
    op.drop_column("news_labels", "collection_run_id")

    op.drop_column("news_collection_runs", "db_tx_id")
    op.drop_column("news_collection_runs", "db_recorded_at")

    op.drop_index("ix_eval_reassess_corr_target_id", table_name="forecast_evaluation_reassessments")
    op.drop_index("ix_forecast_evaluation_reassessments_forecast_id", table_name="forecast_evaluation_reassessments")
    op.drop_index("ix_forecast_evaluation_reassessments_reassessment_id", table_name="forecast_evaluation_reassessments")
    op.drop_table("forecast_evaluation_reassessments")

    op.drop_column("forecast_evaluations", "model_version")
    op.drop_column("forecast_evaluations", "protocol_version")

    op.execute("DROP INDEX IF EXISTS uq_prospective_origin_publication;")
    op.drop_index("ix_forecast_runs_origin_source_published_at", table_name="forecast_runs")
    op.drop_column("forecast_runs", "origin_source_published_at")
    op.drop_column("forecast_runs", "protocol_sha256")

    op.drop_index("ix_research_feature_snapshots_origin_source_published_at", table_name="research_feature_snapshots")
    op.drop_column("research_feature_snapshots", "protocol_sha256")
    op.drop_column("research_feature_snapshots", "origin_source_published_at")

    op.execute("DROP INDEX IF EXISTS uq_bullion_mjdta_pub_revision;")
    if dialect != "sqlite":
        op.drop_constraint("fk_bullion_obs_supersedes", "bullion_rate_observations", type_="foreignkey")
    op.drop_column("bullion_rate_observations", "correction_reason")
    op.drop_column("bullion_rate_observations", "supersedes_observation_id")
    op.drop_column("bullion_rate_observations", "revision_number")
    op.drop_column("bullion_rate_observations", "observation_kind")
    op.drop_column("bullion_rate_observations", "is_timestamp_inferred")
    op.drop_column("bullion_rate_observations", "source_timestamp_precision")
    op.drop_column("bullion_rate_observations", "raw_source_published_time")
