"""Comprehensive adversarial & regression tests for Audit #3 Final Remediation (A3-FINAL-1 .. A3-FINAL-7)."""
from __future__ import annotations

import importlib
import linecache
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from app.models.bullion import BullionRateObservation
from app.models.research import (
    ForecastEvaluation,
    ForecastEvaluationReassessment,
    ForecastRun,
    NewsArticleRecord,
    NewsCluster,
    NewsCollectionRun,
    NewsLabelRecord,
    ResearchFeatureSnapshot,
)
from app.services.kjpl.city_parser import _build_validated_item, parse_kjpl_all_city_rates
from app.services.kjpl.city_schemas import ParsedKJPLPayload
from app.services.kjpl.parser import resolve_clock_only_kjpl_time, resolve_clock_only_kjpl_timestamp
from app.services.kjpl.persistence import persist_parsed_payload, seed_bullion_metadata
from app.services.ollama.classifier import OllamaGoldClassifier, is_ollama_enabled
from app.services.prediction import forecast_engine as fe
from app.services.prediction.mjdta_series import load_mjdta_observations_from_db
from app.services.prediction.news_features import compute_news_features_at_cutoff, load_eligible_news_records_from_db
from app.services.prediction.protocol import (
    EXPERIMENT_PROTOCOL_V1_SHA256,
    EXPERIMENT_PROTOCOL_VERSION,
    PROTOCOL_DOC_PATH,
    ProtocolIntegrityError,
    verify_runtime_protocol,
)
from app.services.sentiment.label_store import _classifier_implementation_digest, persist_news_collection_to_db
from app.services.sentiment.provenance import assign_story_clusters, compute_cluster_implementation_digest
from app.services.sentiment.schemas import (
    GeneralTone,
    GoldImpactDirection,
    GoldMacroDriver,
    GoldSentimentResult,
    MacroSurprise,
    NewsArticle,
)
from tests.test_research_forecast_and_leakage import _setup_migrated_sqlite_session

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
DB_ERRORS = (IntegrityError, OperationalError, DBAPIError, ProgrammingError)


def _utc(y: int, m: int, d: int, h: int = 10, minute: int = 0) -> datetime:
    return datetime(y, m, d, h, minute, 0, tzinfo=UTC)


def _mjdta_item(price: float):
    return _build_validated_item(
        city_code="CHENNAI",
        city_display_name="Chennai",
        product_id="MJDTA_GOLD_24K",
        product_name="MJDTA Gold 24K Benchmark (Excl. GST)",
        metal="GOLD",
        purity=0.999,
        weight=1.0,
        unit="1g",
        rate_type="MJDTA_BENCHMARK",
        price=price,
        currency="INR",
        source_product_id="MJDTA_GOLD",
        raw_source_name="MJDTA GOLD (Without GST)",
    )


def _seed_mjdta_history(db, start_dt: datetime, n: int = 18, step: float = 25.0) -> list[datetime]:
    seed_bullion_metadata(db, ensure_schema=False)
    pubs: list[datetime] = []
    for k in range(n):
        pub_dt = start_dt + timedelta(days=k)
        obs_dt = pub_dt + timedelta(minutes=15)
        db.add(
            BullionRateObservation(
                city_code="CHENNAI",
                product_id="MJDTA_GOLD_24K",
                source_product_id="MJDTA_GOLD",
                price=Decimal(str(13000.0 + k * step)),
                currency="INR",
                rate_type="MJDTA_BENCHMARK",
                unit="1g",
                normalized_price_per_gram=Decimal(str(13000.0 + k * step)),
                source_url="http://www.kjpl.in/",
                source_published_at=pub_dt,
                raw_source_published_time=pub_dt.strftime("%d-%m-%Y %I:%M:%S %p"),
                source_timestamp_precision="FULL",
                is_timestamp_inferred=False,
                observed_at=obs_dt,
                observation_kind="ORIGINAL",
                revision_number=1,
                is_changed=True,
                freshness_status="FRESH",
                validation_status="VALID",
            )
        )
        pubs.append(pub_dt)
    db.commit()
    return pubs


# ---------------------------------------------------------------------------
# A3-FINAL-1A: Prevent Forged Research Inserts (forecast_evaluations)
# ---------------------------------------------------------------------------
def test_a3_final_1a_rejects_forged_prospective_evaluations(tmp_path: Path, monkeypatch):
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "final1a.db", monkeypatch)
    import app.db.session as dbs

    try:
        with Session() as db:
            pubs = _seed_mjdta_history(db, _utc(2026, 9, 1, 4, 0), n=18)
            frontier_obs_dt = pubs[-1] + timedelta(minutes=15)
            gen1 = frontier_obs_dt + timedelta(minutes=10)
            res = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1)
            assert res["status"] == "PROSPECTIVE_FORECAST_LOGGED"

            h1_run = db.execute(
                select(ForecastRun).where(
                    ForecastRun.generation_mode == "PROSPECTIVE",
                    ForecastRun.arm == "NO_CHANGE",
                    ForecastRun.horizon_publications == 1,
                )
            ).scalar_one()
            h3_run = db.execute(
                select(ForecastRun).where(
                    ForecastRun.generation_mode == "PROSPECTIVE",
                    ForecastRun.arm == "NO_CHANGE",
                    ForecastRun.horizon_publications == 3,
                )
            ).scalar_one()

            # Add an unrelated ALL_INDIA row (invalid as MJDTA target) and 1 genuine h=1 post-origin obs
            bad_tgt = BullionRateObservation(
                city_code="ALL_INDIA",
                product_id="MJDTA_GOLD_24K",
                source_product_id="GOLD",
                price=Decimal("14000.00"),
                currency="INR",
                rate_type="MJDTA_BENCHMARK",
                unit="1g",
                normalized_price_per_gram=Decimal("14000.00"),
                source_published_at=pubs[-1] + timedelta(hours=12),
                observed_at=pubs[-1] + timedelta(hours=12, minutes=5),
                validation_status="VALID",
            )
            db.add(bad_tgt)
            db.flush()
            bad_tgt_id = bad_tgt.id

            # 1) Fabricated evaluation for an UNMATURED h=1 forecast (before any MJDTA target exists)
            with pytest.raises(DB_ERRORS):
                db.execute(
                    text(
                        """
                        INSERT INTO forecast_evaluations
                        (forecast_id, protocol_version, model_version, generation_mode, arm, horizon_publications,
                         origin_observed_at, target_observation_id, matured_observed_at, actual_price_inr_per_g,
                         actual_log_return, actual_direction, is_non_overlapping_origin, evaluated_at)
                        VALUES (:fid, :pv, :mv, 'PROSPECTIVE', 'NO_CHANGE', 1, :orig, :tid, :mat, 14000.0, 0.04, 'UP', 1, :ev)
                        """
                    ),
                    {
                        "fid": h1_run.forecast_id,
                        "pv": h1_run.protocol_version,
                        "mv": h1_run.model_version,
                        "orig": h1_run.origin_observed_at,
                        "tid": bad_tgt_id,
                        "mat": bad_tgt.observed_at,
                        "ev": bad_tgt.observed_at,
                    },
                )
                db.commit()
            db.rollback()

            # Insert 2 genuine post-origin MJDTA publications (so h=1 matures, h=3 is STILL unmatured!)
            t_plus_1_pub = pubs[-1] + timedelta(days=1)
            t_plus_2_pub = pubs[-1] + timedelta(days=2)
            t1_obs = BullionRateObservation(
                city_code="CHENNAI", product_id="MJDTA_GOLD_24K", source_product_id="MJDTA_GOLD",
                price=Decimal("13600.00"), normalized_price_per_gram=Decimal("13600.00"),
                currency="INR", rate_type="MJDTA_BENCHMARK", unit="1g",
                source_published_at=t_plus_1_pub, observed_at=t_plus_1_pub + timedelta(minutes=15),
                observation_kind="ORIGINAL", revision_number=1, validation_status="VALID",
            )
            t2_obs = BullionRateObservation(
                city_code="CHENNAI", product_id="MJDTA_GOLD_24K", source_product_id="MJDTA_GOLD",
                price=Decimal("13700.00"), normalized_price_per_gram=Decimal("13700.00"),
                currency="INR", rate_type="MJDTA_BENCHMARK", unit="1g",
                source_published_at=t_plus_2_pub, observed_at=t_plus_2_pub + timedelta(minutes=15),
                observation_kind="ORIGINAL", revision_number=1, validation_status="VALID",
            )
            db.add_all([t1_obs, t2_obs])
            db.commit()

            # 2) h=3 forecast evaluated against h=1 or h=2 target (horizon not satisfied) -> REJECTED
            with pytest.raises(DB_ERRORS):
                db.execute(
                    text(
                        """
                        INSERT INTO forecast_evaluations
                        (forecast_id, protocol_version, model_version, generation_mode, arm, horizon_publications,
                         origin_observed_at, target_observation_id, matured_observed_at, actual_price_inr_per_g,
                         actual_log_return, actual_direction, is_non_overlapping_origin, evaluated_at)
                        VALUES (:fid, :pv, :mv, 'PROSPECTIVE', 'NO_CHANGE', 3, :orig, :tid, :mat, 13700.0, 0.02, 'UP', 1, :ev)
                        """
                    ),
                    {
                        "fid": h3_run.forecast_id,
                        "pv": h3_run.protocol_version,
                        "mv": h3_run.model_version,
                        "orig": h3_run.origin_observed_at,
                        "tid": t2_obs.id,
                        "mat": t2_obs.observed_at,
                        "ev": t2_obs.observed_at,
                    },
                )
                db.commit()
            db.rollback()

            # 3) h=1 forecast evaluated with tampered actual_price / actual_log_return -> REJECTED
            with pytest.raises(DB_ERRORS):
                db.execute(
                    text(
                        """
                        INSERT INTO forecast_evaluations
                        (forecast_id, protocol_version, model_version, generation_mode, arm, horizon_publications,
                         origin_observed_at, target_observation_id, matured_observed_at, actual_price_inr_per_g,
                         actual_log_return, actual_direction, is_non_overlapping_origin, evaluated_at)
                        VALUES (:fid, :pv, :mv, 'PROSPECTIVE', 'NO_CHANGE', 1, :orig, :tid, :mat, 19999.0, 0.4, 'UP', 1, :ev)
                        """
                    ),
                    {
                        "fid": h1_run.forecast_id,
                        "pv": h1_run.protocol_version,
                        "mv": h1_run.model_version,
                        "orig": h1_run.origin_observed_at,
                        "tid": t1_obs.id,
                        "mat": t1_obs.observed_at,
                        "ev": t1_obs.observed_at,
                    },
                )
                db.commit()
            db.rollback()

            # 4) h=1 forecast with mismatched arm / model_version / fabricated matured_observed_at -> REJECTED
            for bad_field, bad_val in [("arm", "HYBRID"), ("model_version", "FAKE_MODEL"), ("matured_observed_at", t2_obs.observed_at)]:
                params = {
                    "fid": h1_run.forecast_id,
                    "pv": h1_run.protocol_version,
                    "mv": h1_run.model_version,
                    "arm": "NO_CHANGE",
                    "orig": h1_run.origin_observed_at,
                    "tid": t1_obs.id,
                    "mat": t1_obs.observed_at,
                    "ev": t1_obs.observed_at,
                    "lr": float(Decimal("13600") / h1_run.origin_price_inr_per_g),
                }
                import math
                params["lr"] = round(math.log(13600.0 / float(h1_run.origin_price_inr_per_g)), 6)
                if bad_field == "arm":
                    params["arm"] = bad_val
                elif bad_field == "model_version":
                    params["mv"] = bad_val
                else:
                    params["mat"] = bad_val
                with pytest.raises(DB_ERRORS):
                    db.execute(
                        text(
                            """
                            INSERT INTO forecast_evaluations
                            (forecast_id, protocol_version, model_version, generation_mode, arm, horizon_publications,
                             origin_observed_at, target_observation_id, matured_observed_at, actual_price_inr_per_g,
                             actual_log_return, actual_direction, is_non_overlapping_origin, evaluated_at)
                            VALUES (:fid, :pv, :mv, 'PROSPECTIVE', :arm, 1, :orig, :tid, :mat, 13600.0, :lr, 'UP', 1, :ev)
                            """
                        ),
                        params,
                    )
                    db.commit()
                db.rollback()

            # 5) PROSPECTIVE evaluation attached to a BACKTEST forecast -> REJECTED
            bt_fid = f"fc_bt_{uuid.uuid4().hex[:8]}"
            snap_id = db.execute(select(ResearchFeatureSnapshot.snapshot_id).limit(1)).scalar_one()
            db.execute(
                text(
                    """
                    INSERT INTO forecast_runs
                    (forecast_id, protocol_version, generation_mode, model_version, arm, horizon_publications,
                     generated_at, cutoff_time, origin_observation_id, origin_observed_at, origin_price_inr_per_g,
                     snapshot_id, predicted_direction, status, is_immutable, created_at)
                    VALUES (:fid, 'EXPERIMENT_PROTOCOL_V1', 'BACKTEST', 'RIDGE_STD_V1', 'NO_CHANGE', 1,
                            :orig, :orig, :oid, :orig, 13425.0, :sid, 'FLAT', 'BACKTEST_EVALUATED', 1, :orig)
                    """
                ),
                {"fid": bt_fid, "orig": h1_run.origin_observed_at, "oid": h1_run.origin_observation_id, "sid": snap_id},
            )
            db.commit()
            with pytest.raises(DB_ERRORS):
                db.execute(
                    text(
                        """
                        INSERT INTO forecast_evaluations
                        (forecast_id, protocol_version, model_version, generation_mode, arm, horizon_publications,
                         origin_observed_at, target_observation_id, matured_observed_at, actual_price_inr_per_g,
                         actual_log_return, actual_direction, is_non_overlapping_origin, evaluated_at)
                        VALUES (:fid, 'EXPERIMENT_PROTOCOL_V1', 'RIDGE_STD_V1', 'PROSPECTIVE', 'NO_CHANGE', 1,
                                :orig, :tid, :mat, 13600.0, 0.013, 'UP', 1, :ev)
                        """
                    ),
                    {"fid": bt_fid, "orig": h1_run.origin_observed_at, "tid": t1_obs.id, "mat": t1_obs.observed_at, "ev": t1_obs.observed_at},
                )
                db.commit()
            db.rollback()

            # 6) Legitimate maturation succeeds cleanly for the 4 h=1 arms
            mat_res = fe.evaluate_matured_prospective_forecasts(db)
            assert mat_res["prospective_evaluations_inserted"] == 4
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


# ---------------------------------------------------------------------------
# A3-FINAL-1B: News-Label Temporal Provenance
# ---------------------------------------------------------------------------
def test_a3_final_1b_rejects_backdated_or_forged_news_labels(tmp_path: Path, monkeypatch):
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "final1b.db", monkeypatch)
    import app.db.session as dbs

    try:
        t_run = _utc(2026, 10, 10, 12, 0)
        with Session() as db:
            art = NewsArticle(
                title="Fed cuts interest rates sharply, boosting gold",
                url="https://example.com/fed-cut-1b",
                source="Reuters",
                published_at=t_run - timedelta(hours=2),
                ingested_at=t_run,
                first_seen_at=t_run,
            )
            d = assign_story_clusters([{"published_at": art.published_at, "title": art.title}])[0]
            art.story_cluster_id, art.cluster_key, art.cluster_version = d["story_cluster_id"], d["cluster_key"], d["cluster_version"]
            persist_news_collection_to_db(
                db,
                run_id="run_1b",
                started_at=t_run - timedelta(minutes=5),
                completed_at=t_run,
                status="SUCCESS",
                articles=[art],
                health={"queries_attempted": 5, "queries_succeeded": 5, "queries_failed": 0},
                stats={},
                label_created_at=t_run,
            )
            art_row = db.execute(select(NewsArticleRecord)).scalar_one()

            # 1) Label with label_created_at BEFORE article first_seen_at -> REJECTED
            with pytest.raises(DB_ERRORS):
                db.execute(
                    text(
                        """
                        INSERT INTO news_labels
                        (article_id, story_cluster_id, collection_run_id, classification_scope, label_created_at,
                         db_recorded_at, available_at, sentiment_version, model_name, general_tone, gold_impact,
                         driver, surprise, is_price_report, feature_eligible, confidence, is_human_verified)
                        VALUES (:aid, :cid, NULL, 'CLUSTER', :bad_ts, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                                'GOLD_SENTIMENT_V3', 'forged_model', 'POSITIVE', 'BEARISH', 'FED_POLICY', 'UNKNOWN', 0, 1, 'HIGH', 0)
                        """
                    ),
                    {"aid": art_row.id, "cid": art_row.story_cluster_id, "bad_ts": t_run - timedelta(hours=1)},
                )
                db.commit()
            db.rollback()

            # 2) Label referencing nonexistent cluster -> REJECTED
            with pytest.raises(DB_ERRORS):
                db.execute(
                    text(
                        """
                        INSERT INTO news_labels
                        (article_id, story_cluster_id, collection_run_id, classification_scope, label_created_at,
                         db_recorded_at, available_at, sentiment_version, model_name, general_tone, gold_impact,
                         driver, surprise, is_price_report, feature_eligible, confidence, is_human_verified)
                        VALUES (:aid, 'nonexistent_clu', NULL, 'CLUSTER', :ok_ts, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                                'GOLD_SENTIMENT_V3', 'forged_model', 'POSITIVE', 'BEARISH', 'FED_POLICY', 'UNKNOWN', 0, 1, 'HIGH', 0)
                        """
                    ),
                    {"aid": art_row.id, "ok_ts": t_run + timedelta(minutes=5)},
                )
                db.commit()
            db.rollback()

            # 3) Unlinked label trying to forge historical available_at -> REJECTED in SQLite (or pinned NOW() in PG)
            with pytest.raises(DB_ERRORS):
                db.execute(
                    text(
                        """
                        INSERT INTO news_labels
                        (article_id, story_cluster_id, collection_run_id, classification_scope, label_created_at,
                         db_recorded_at, available_at, sentiment_version, model_name, general_tone, gold_impact,
                         driver, surprise, is_price_report, feature_eligible, confidence, is_human_verified)
                        VALUES (:aid, :cid, NULL, 'CLUSTER', :ok_ts, CURRENT_TIMESTAMP, :forged_avail,
                                'GOLD_SENTIMENT_V3', 'forged_model', 'POSITIVE', 'BEARISH', 'FED_POLICY', 'UNKNOWN', 0, 1, 'HIGH', 0)
                        """
                    ),
                    {"aid": art_row.id, "cid": art_row.story_cluster_id, "ok_ts": t_run + timedelta(minutes=5), "forged_avail": t_run + timedelta(minutes=5)},
                )
                db.commit()
            db.rollback()

            # 4) Historical cutoff query strictly sees ONLY legitimate run_1b label (+1.0), never forged rows
            recs, runs = load_eligible_news_records_from_db(db, cutoff_time=t_run + timedelta(minutes=30))
            feats = compute_news_features_at_cutoff(t_run + timedelta(minutes=30), recs, runs)
            assert feats.coverage_ok is True
            assert feats.net_impact == 1.0
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


# ---------------------------------------------------------------------------
# A3-FINAL-3: Corrected MJDTA Frontier Forecasts & Reassessment
# ---------------------------------------------------------------------------
def test_a3_final_3_correction_lineage_no_duplicate_prospective_and_reassessment(tmp_path: Path, monkeypatch):
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "final3.db", monkeypatch)
    import app.db.session as dbs

    try:
        with Session() as db:
            pubs = _seed_mjdta_history(db, _utc(2026, 9, 1, 4, 0), n=18)
            frontier_pub = pubs[-1]  # 2026-09-18 04:00Z, price=13425.0
            gen1 = frontier_pub + timedelta(minutes=30)

            r1 = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1)
            assert r1["status"] == "PROSPECTIVE_FORECAST_LOGGED"
            assert r1["persisted"] == {"snapshots_inserted": 1, "prospective_forecasts_inserted": 8}

            # 1) Same publication, same price repeated -> idempotent, 0 rows added
            p_same = persist_parsed_payload(
                ParsedKJPLPayload(
                    observed_at=gen1 + timedelta(minutes=10),
                    pipeline="MJDTA",
                    source_updated_time=frontier_pub.astimezone(IST).strftime("%d-%m-%Y %I:%M:%S %p"),
                    source_updated_at=frontier_pub.astimezone(IST),
                    source_timestamp_precision="FULL",
                    city_rates=[_mjdta_item(13425.0)],
                ),
                session=db,
                mirror_csv=False,
            )
            assert p_same["records_inserted"] == 0

            # 2) Same publication, corrected price (13425 -> 13499)
            corr_obs_dt = gen1 + timedelta(minutes=20)
            orig_row = db.execute(
                select(BullionRateObservation).where(BullionRateObservation.source_published_at == frontier_pub)
            ).scalar_one()

            # Simulate real clock at corr_obs_dt for persist_parsed_payload
            import app.services.kjpl.persistence as P_mod
            orig_dt_cls = P_mod.datetime
            class _FrozenDT(datetime):
                @classmethod
                def now(cls, tz=None):
                    return corr_obs_dt if tz is None else corr_obs_dt.astimezone(tz)
            P_mod.datetime = _FrozenDT
            try:
                p_corr = persist_parsed_payload(
                    ParsedKJPLPayload(
                        observed_at=corr_obs_dt,
                        pipeline="MJDTA",
                        source_updated_time=frontier_pub.astimezone(IST).strftime("%d-%m-%Y %I:%M:%S %p"),
                        source_updated_at=frontier_pub.astimezone(IST),
                        source_timestamp_precision="FULL",
                        city_rates=[_mjdta_item(13499.0)],
                    ),
                    session=db,
                    mirror_csv=False,
                )
                # Correction replay (same corrected price again) -> idempotent!
                p_replay = persist_parsed_payload(
                    ParsedKJPLPayload(
                        observed_at=corr_obs_dt + timedelta(minutes=5),
                        pipeline="MJDTA",
                        source_updated_time=frontier_pub.astimezone(IST).strftime("%d-%m-%Y %I:%M:%S %p"),
                        source_updated_at=frontier_pub.astimezone(IST),
                        source_timestamp_precision="FULL",
                        city_rates=[_mjdta_item(13499.0)],
                    ),
                    session=db,
                    mirror_csv=False,
                )
                # Second correction (13499 -> 13510) -> rev 3
                p_corr2 = persist_parsed_payload(
                    ParsedKJPLPayload(
                        observed_at=corr_obs_dt + timedelta(minutes=10),
                        pipeline="MJDTA",
                        source_updated_time=frontier_pub.astimezone(IST).strftime("%d-%m-%Y %I:%M:%S %p"),
                        source_updated_at=frontier_pub.astimezone(IST),
                        source_timestamp_precision="FULL",
                        city_rates=[_mjdta_item(13510.0)],
                    ),
                    session=db,
                    mirror_csv=False,
                )
            finally:
                P_mod.datetime = orig_dt_cls

            assert p_corr["records_inserted"] == 1
            assert p_replay["records_inserted"] == 0
            assert p_corr2["records_inserted"] == 1

            revs = db.execute(
                select(BullionRateObservation)
                .where(BullionRateObservation.source_published_at == frontier_pub)
                .order_by(BullionRateObservation.revision_number.asc())
            ).scalars().all()
            assert [(r.observation_kind, r.revision_number, float(r.price)) for r in revs] == [
                ("ORIGINAL", 1, 13425.0),
                ("CORRECTION", 2, 13499.0),
                ("CORRECTION", 3, 13510.0),
            ]
            assert revs[1].supersedes_observation_id == orig_row.id
            assert revs[2].supersedes_observation_id == revs[1].id

            # Point-in-time isolation: as_of BEFORE correction sees 13425.0; AFTER sees 13510.0
            obs_before, _ = load_mjdta_observations_from_db(db, as_of=gen1)
            obs_after, _ = load_mjdta_observations_from_db(db, as_of=corr_obs_dt + timedelta(minutes=20))
            assert obs_before[-1].gold_mjdta_inr_per_g == 13425.0
            assert obs_after[-1].gold_mjdta_inr_per_g == 13510.0

            # 3) Prospective frontier run AFTER correction NEVER generates a second 8-arm set
            r2 = fe.generate_prospective_forecast_for_frontier(db, generated_at=corr_obs_dt + timedelta(minutes=20))
            assert r2["status"] == "PROSPECTIVE_ALREADY_LOGGED_FOR_PUBLICATION"
            assert r2["correction_detected"] is True
            assert r2["persisted"] == {"snapshots_inserted": 0, "prospective_forecasts_inserted": 0}
            assert db.query(ForecastRun).filter(ForecastRun.generation_mode == "PROSPECTIVE").count() == 8
            # Original forecast retains 13425.0
            assert float(db.query(ForecastRun).first().origin_price_inr_per_g) == 13425.0

            # 4) Next day's NEW publication arrives -> generates NEW 8-arm set & matures h=1 original
            next_pub = frontier_pub + timedelta(days=1)
            db.add(
                BullionRateObservation(
                    city_code="CHENNAI", product_id="MJDTA_GOLD_24K", source_product_id="MJDTA_GOLD",
                    price=Decimal("13600.00"), normalized_price_per_gram=Decimal("13600.00"),
                    currency="INR", rate_type="MJDTA_BENCHMARK", unit="1g",
                    source_published_at=next_pub, observed_at=next_pub + timedelta(minutes=15),
                    observation_kind="ORIGINAL", revision_number=1, validation_status="VALID",
                )
            )
            db.commit()
            r3 = fe.generate_prospective_forecast_for_frontier(db, generated_at=next_pub + timedelta(minutes=30))
            assert r3["status"] == "PROSPECTIVE_FORECAST_LOGGED"
            assert r3["persisted"] == {"snapshots_inserted": 1, "prospective_forecasts_inserted": 8}
            assert r3["matured_evaluations_inserted"] == 4  # 4 h=1 arms for frontier_pub matured at 13600.0

            # 5) Later target correction on next_pub -> preserves original ForecastEvaluation & writes ForecastEvaluationReassessment
            orig_next = db.execute(
                select(BullionRateObservation).where(BullionRateObservation.source_published_at == next_pub)
            ).scalar_one()
            db.add(
                BullionRateObservation(
                    city_code="CHENNAI", product_id="MJDTA_GOLD_24K", source_product_id="MJDTA_GOLD",
                    price=Decimal("13655.00"), normalized_price_per_gram=Decimal("13655.00"),
                    currency="INR", rate_type="MJDTA_BENCHMARK", unit="1g",
                    source_published_at=next_pub, observed_at=next_pub + timedelta(hours=3),
                    observation_kind="CORRECTION", revision_number=2, supersedes_observation_id=orig_next.id,
                    correction_reason="Target price corrected", validation_status="VALID",
                )
            )
            db.commit()
            reass = fe.evaluate_matured_prospective_forecasts(db)
            assert reass["prospective_evaluations_inserted"] == 0
            assert reass["prospective_reassessments_inserted"] == 4
            assert float(db.query(ForecastEvaluation).first().actual_price_inr_per_g) == 13600.0
            assert float(db.query(ForecastEvaluationReassessment).first().corrected_actual_price_inr_per_g) == 13655.0
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


# ---------------------------------------------------------------------------
# A3-FINAL-4: Clock-Only Timestamp Safety
# ---------------------------------------------------------------------------
def test_a3_final_4_clock_only_safety_and_all_skew_cases(tmp_path: Path, monkeypatch):
    # 1) Clock ahead by 1, 5, 6, 10, 30 min -> ALL rejected/ambiguous (never future, never guessed as yesterday!)
    now = datetime(2026, 11, 11, 9, 30, tzinfo=IST)
    for delta_min in (1, 5, 6, 10, 30):
        future_clock = (now + timedelta(minutes=delta_min)).strftime("%I:%M %p").lower()
        clk_res = resolve_clock_only_kjpl_timestamp(future_clock, now)
        assert clk_res.timestamp_ist is None, f"Clock +{delta_min}m should be ambiguous, got {clk_res}"
        assert clk_res.precision_status == "AMBIGUOUS_CLOCK_ONLY"
        assert clk_res.is_inferred is True

    # 2) Normal 09:30 publication & immediate poll after publication
    res_exact = resolve_clock_only_kjpl_timestamp("09:30 am", now)
    assert res_exact.timestamp_ist == now
    assert res_exact.precision_status == "INFERRED_CLOCK_ONLY"

    res_after = resolve_clock_only_kjpl_timestamp("09:30 am", now + timedelta(minutes=1))
    assert res_after.timestamp_ist == now

    # 3) Midnight crossing: 00:10 IST polling 11:50 pm -> yesterday 23:50 IST
    midnight_now = datetime(2026, 11, 12, 0, 10, tzinfo=IST)
    res_mid = resolve_clock_only_kjpl_timestamp("11:50 pm", midnight_now)
    assert res_mid.timestamp_ist == datetime(2026, 11, 11, 23, 50, tzinfo=IST)
    assert res_mid.is_inferred is True

    # 3b) Direct caller contract for valid, inferred, and quarantined clock-only parsing
    assert resolve_clock_only_kjpl_time("09:30 am", now) == now
    assert resolve_clock_only_kjpl_time("11:50 pm", midnight_now) == datetime(2026, 11, 11, 23, 50, tzinfo=IST)
    assert resolve_clock_only_kjpl_time("09:31 am", now) is None
    assert resolve_clock_only_kjpl_time("09:34 am", now) is None
    parsed_quarantined = parse_kjpl_all_city_rates(
        "<html><span class='gold-rate'>13400</span><span class='mjdma_data'>Time : 09:34 am</span></html>",
        reference_time=now,
    )
    assert parsed_quarantined.source_updated_at is None
    assert parsed_quarantined.source_timestamp_precision == "AMBIGUOUS_CLOCK_ONLY"

    # 4) Persistence diagnostics for ambiguous clock-only, 06:08 pre-open without carryover, weekend/closed carryover, and FULL future
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "final4.db", monkeypatch)
    import app.db.session as dbs
    import app.services.kjpl.persistence as P_mod

    orig_dt = P_mod.datetime
    try:
        with Session() as db:
            seed_bullion_metadata(db, ensure_schema=False)

            def _run_clock_poll(obs_ist: datetime, raw_clock: str, price: float, market_status: str = "OPEN", prec: str | None = None):
                class _FD(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        u = obs_ist.astimezone(UTC)
                        return u if tz is None else u.astimezone(tz)
                P_mod.datetime = _FD
                pub_ist = parse_kjpl_all_city_rates(
                    f"<html><span class='gold-rate'>{price}</span><span class='mjdma_data'>{raw_clock}</span></html>",
                    reference_time=obs_ist,
                )
                return persist_parsed_payload(
                    ParsedKJPLPayload(
                        observed_at=obs_ist.astimezone(UTC),
                        pipeline="KJPL_MJDTA",
                        source_updated_time=raw_clock,
                        source_updated_at=pub_ist.source_updated_at,
                        source_timestamp_precision=prec or pub_ist.source_timestamp_precision,
                        market_status=market_status,
                        city_rates=[_mjdta_item(price)],
                    ),
                    session=db,
                    mirror_csv=False,
                )

            # 06:08 IST poll BEFORE publication with NO prior carryover -> QUARANTINED (never invents yesterday!)
            r_0608 = _run_clock_poll(datetime(2026, 9, 22, 6, 8, tzinfo=IST), "Time : 09:29 am", 14270.0)
            assert r_0608["records_quarantined"] == 1
            assert db.query(BullionRateObservation).filter_by(validation_status="VALID").count() == 0

            # Clock ahead by 5 min and 6 min at 09:30 -> QUARANTINED with raw clock preserved
            r_skew5 = _run_clock_poll(datetime(2026, 9, 22, 9, 30, tzinfo=IST), "Time : 09:35 am", 14275.0)
            r_skew6 = _run_clock_poll(datetime(2026, 9, 22, 9, 30, tzinfo=IST), "Time : 09:36 am", 14275.0)
            assert r_skew5["records_quarantined"] == 1
            assert r_skew6["records_quarantined"] == 1
            ambig = db.query(BullionRateObservation).filter_by(source_timestamp_precision="AMBIGUOUS_CLOCK_ONLY").all()
            assert len(ambig) == 3
            assert all(r.source_published_at is None and r.raw_source_published_time is not None for r in ambig)

            # FULL timestamp 1 min in the future -> NEVER valid (MJDTA_FUTURE_TOLERANCE = 0)
            obs_t = datetime(2026, 9, 22, 10, 0, tzinfo=IST)
            class _FD2(datetime):
                @classmethod
                def now(cls, tz=None):
                    u = obs_t.astimezone(UTC)
                    return u if tz is None else u.astimezone(tz)
            P_mod.datetime = _FD2
            r_full_future = persist_parsed_payload(
                ParsedKJPLPayload(
                    observed_at=obs_t.astimezone(UTC),
                    pipeline="MJDTA",
                    source_updated_time="22-09-2026 10:01:00 am",
                    source_updated_at=obs_t + timedelta(minutes=1),
                    source_timestamp_precision="FULL",
                    city_rates=[_mjdta_item(14300.0)],
                ),
                session=db,
                mirror_csv=False,
            )
            assert r_full_future["records_quarantined"] == 1

            # Genuine FULL publication at 09:30, then next day FULL same-time unchanged price -> BOTH VALID (2 rows)
            for day_num in (23, 24):
                pub_d = datetime(2026, 9, day_num, 9, 30, tzinfo=IST)
                obs_d = datetime(2026, 9, day_num, 10, 0, tzinfo=IST)
                class _FD3(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        u = obs_d.astimezone(UTC)
                        return u if tz is None else u.astimezone(tz)
                P_mod.datetime = _FD3
                persist_parsed_payload(
                    ParsedKJPLPayload(
                        observed_at=obs_d.astimezone(UTC),
                        pipeline="MJDTA",
                        source_updated_time=pub_d.strftime("%d-%m-%Y %I:%M:%S %p"),
                        source_updated_at=pub_d,
                        source_timestamp_precision="FULL",
                        city_rates=[_mjdta_item(14300.0)],
                    ),
                    session=db,
                    mirror_csv=False,
                )
            assert db.query(BullionRateObservation).filter_by(validation_status="VALID").count() == 2

            # Day 25 CLOSED market / carryover CLOCK_ONLY -> quarantined diagnostic row visible (not silently dropped!)
            r_closed = _run_clock_poll(datetime(2026, 9, 25, 11, 0, tzinfo=IST), "Time : 09:30 am", 14300.0, market_status="CLOSED")
            assert r_closed["records_quarantined"] == 1
            assert db.query(BullionRateObservation).filter_by(validation_status="VALID").count() == 2
            assert db.query(BullionRateObservation).filter_by(validation_status="QUARANTINED").count() == 5
    finally:
        P_mod.datetime = orig_dt
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


# ---------------------------------------------------------------------------
# A3-FINAL-5: Ollama Concurrent Write Safety & Default Disabled Policy
# ---------------------------------------------------------------------------
def test_a3_final_5_ollama_concurrent_db_idempotency_and_default_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OLLAMA_ENABLED", raising=False)
    assert is_ollama_enabled() is False

    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "final5.db", monkeypatch)
    import app.db.session as dbs

    try:
        clf = OllamaGoldClassifier.__new__(OllamaGoldClassifier)
        fixed = GoldSentimentResult(
            general_tone=GeneralTone.NEUTRAL,
            gold_impact=GoldImpactDirection.BULLISH,
            driver=GoldMacroDriver.FED_POLICY,
            surprise=MacroSurprise.UNKNOWN,
            is_price_report=False,
            confidence="HIGH",
            evidence_rationale="Concurrent test",
            sentiment_version="GOLD_OLLAMA_V2",
            model_name="qwen3.5:4b",
            model_digest="digest123",
            prompt_version="GOLD_OLLAMA_PROMPT_V1",
        )
        monkeypatch.setattr(clf, "classify_headline", lambda **kw: fixed, raising=False)

        barrier = threading.Barrier(2)
        errors: list[str] = []

        def worker():
            s = Session()
            try:
                barrier.wait()
                clf.classify_and_persist(s, story_cluster_id="clu_ollama_conc", title="Fed cuts rates")
                # Verify session is NOT poisoned after potential concurrent IntegrityError
                assert s.execute(select(func.count()).select_from(NewsLabelRecord)).scalar() >= 1
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                s.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        with Session() as db:
            rows = db.execute(
                select(NewsLabelRecord).where(NewsLabelRecord.story_cluster_id == "clu_ollama_conc")
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].classification_identity_hash is not None
            assert rows[0].classification_scope == "CLUSTER"
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


# ---------------------------------------------------------------------------
# A3-FINAL-6: Protocol Hash Runtime Enforcement
# ---------------------------------------------------------------------------
def test_a3_final_6_protocol_hash_runtime_enforcement(tmp_path: Path, monkeypatch):
    # 1) Unmodified protocol succeeds and matches frozen constant
    sha = verify_runtime_protocol()
    assert sha == EXPERIMENT_PROTOCOL_V1_SHA256

    # 2) One-byte modification fails closed
    tampered = tmp_path / "EXPERIMENT_PROTOCOL_V1.md"
    tampered.write_bytes(PROTOCOL_DOC_PATH.read_bytes().replace(b"MIN_EVALUATION_SAMPLES = 30", b"MIN_EVALUATION_SAMPLES = 20"))
    with pytest.raises(ProtocolIntegrityError):
        verify_runtime_protocol(protocol_path=tampered)

    # 3) Missing protocol file fails closed
    with pytest.raises(ProtocolIntegrityError):
        verify_runtime_protocol(protocol_path=tmp_path / "missing.md")

    # 4) Unregistered / unknown protocol version fails closed
    with pytest.raises(ProtocolIntegrityError):
        verify_runtime_protocol(protocol_version="EXPERIMENT_PROTOCOL_V99")

    # 5) Persisting PROSPECTIVE forecasts stores protocol_sha256, rejects tampered doc, leaves legacy NULL untouched
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "final6.db", monkeypatch)
    import app.db.session as dbs
    try:
        with Session() as db:
            pubs = _seed_mjdta_history(db, _utc(2026, 9, 1, 4, 0), n=12)
            gen1 = pubs[-1] + timedelta(minutes=30)

            # Tamper doc via monkeypatch on PROTOCOL_DOC_PATH -> prospective generation MUST reject
            import app.services.prediction.protocol as proto_mod
            monkeypatch.setattr(proto_mod, "PROTOCOL_DOC_PATH", tampered)
            with pytest.raises(ProtocolIntegrityError):
                fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1)

            # Restore real protocol -> succeeds and stores sha256 on ForecastRun & ResearchFeatureSnapshot
            monkeypatch.setattr(proto_mod, "PROTOCOL_DOC_PATH", PROTOCOL_DOC_PATH)
            out = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1)
            assert out["protocol_sha256"] == EXPERIMENT_PROTOCOL_V1_SHA256
            runs = db.query(ForecastRun).filter_by(generation_mode="PROSPECTIVE").all()
            assert len(runs) == 8 and all(r.protocol_sha256 == EXPERIMENT_PROTOCOL_V1_SHA256 for r in runs)
            snaps = db.query(ResearchFeatureSnapshot).filter_by(generation_mode="PROSPECTIVE").all()
            assert len(snaps) == 1 and snaps[0].protocol_sha256 == EXPERIMENT_PROTOCOL_V1_SHA256

            # Legacy row without protocol_sha256 stays NULL (never falsely marked)
            db.execute(
                text(
                    """
                    INSERT INTO forecast_runs
                    (forecast_id, protocol_version, protocol_sha256, generation_mode, model_version, arm,
                     horizon_publications, generated_at, cutoff_time, origin_observed_at, origin_price_inr_per_g,
                     snapshot_id, predicted_direction, status, is_immutable, created_at)
                    VALUES ('legacy_null_sha', 'EXPERIMENT_PROTOCOL_V1', NULL, 'BACKTEST', 'RIDGE_STD_V1', 'NO_CHANGE',
                            1, :o, :o, :o, 13000.0, :sid, 'FLAT', 'BACKTEST_EVALUATED', 1, :o)
                    """
                ),
                {"o": pubs[0], "sid": snaps[0].snapshot_id},
            )
            db.commit()
            leg = db.execute(select(ForecastRun).where(ForecastRun.forecast_id == "legacy_null_sha")).scalar_one()
            assert leg.protocol_sha256 is None
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()

    # 6) Cross-process & different PYTHONHASHSEED verification
    code = (
        "import sys; sys.path.insert(0, '.'); "
        "from app.services.prediction.protocol import verify_runtime_protocol; "
        "print(verify_runtime_protocol())"
    )
    backend_dir = str(Path(__file__).resolve().parents[1])
    out_hashes = {
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
        ).stdout.strip()
        for seed in (1, 42, 999)
    }
    assert out_hashes == {EXPERIMENT_PROTOCOL_V1_SHA256}


# ---------------------------------------------------------------------------
# A3-FINAL-7: Stable Classifier Fingerprint (Ignores Comments & Docstrings)
# ---------------------------------------------------------------------------
def test_a3_final_7_classifier_fingerprint_ignores_comments_and_docstrings(tmp_path: Path, monkeypatch):
    mod_file = tmp_path / "a3_final7_rules.py"
    base_src = (
        '"""Module docstring v1."""\n'
        "RULE_WORDS = ['rate cut']\n"
        "def helper(t):\n"
        '    """Helper docstring."""\n'
        "    # comment inside helper\n"
        "    return any(w in t.lower() for w in RULE_WORDS)\n"
        "def classify(title):\n"
        '    """Main docstring."""\n'
        "    return 'BULLISH' if helper(title) else 'UNKNOWN'\n"
    )
    mod_file.write_text(base_src)
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = importlib.import_module("a3_final7_rules")
    try:
        d_base = _classifier_implementation_digest(mod.classify)

        # Edit ONLY docstrings & comments -> MUST remain identical
        doc_comment_edit = base_src.replace("Module docstring v1.", "Updated docs!").replace(
            "Helper docstring.", "Edited helper docs"
        ).replace("# comment inside helper", "# completely different comment")
        mod_file.write_text(doc_comment_edit)
        linecache.checkcache(str(mod_file))
        mod = importlib.reload(mod)
        assert _classifier_implementation_digest(mod.classify) == d_base

        # Edit rule-table entry -> MUST change
        mod_file.write_text(base_src.replace("'rate cut'", "'rate hike'"))
        linecache.checkcache(str(mod_file))
        mod = importlib.reload(mod)
        assert _classifier_implementation_digest(mod.classify) != d_base

        # Edit helper logic -> MUST change
        mod_file.write_text(base_src.replace("any(", "all("))
        linecache.checkcache(str(mod_file))
        mod = importlib.reload(mod)
        assert _classifier_implementation_digest(mod.classify) != d_base
    finally:
        sys.modules.pop("a3_final7_rules", None)

    # Cross-process determinism under different PYTHONHASHSEEDs (both classifier & clustering digests)
    backend_dir = str(Path(__file__).resolve().parents[1])
    code = (
        "import sys; sys.path.insert(0, '.'); "
        "from app.services.sentiment.label_store import _classifier_implementation_digest; "
        "from app.services.sentiment.gold_impact import evaluate_gold_impact; "
        "from app.services.sentiment.provenance import compute_cluster_implementation_digest; "
        "print(_classifier_implementation_digest(evaluate_gold_impact), compute_cluster_implementation_digest())"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
        ).stdout.strip()
        for seed in (1, 17, 42)
    }
    assert len(digests) == 1


# ---------------------------------------------------------------------------
# PostgreSQL 16 Full Integration: Role Separation (A3-FINAL-2) + Raw-SQL Attacks
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not Path("/opt/homebrew/opt/postgresql@16/bin/initdb").exists(),
    reason="Local PostgreSQL 16 binaries not installed",
)
def test_a3_final_postgresql_role_security_and_raw_sql_attacks(tmp_path: Path):
    pg_bin = Path("/opt/homebrew/opt/postgresql@16/bin")
    pg_data = tmp_path / "pg16_data"
    pg_log = tmp_path / "pg16.log"
    port = 55439
    repo_root = Path(__file__).resolve().parents[2]
    backend_dir = repo_root / "backend"

    subprocess.run(
        [str(pg_bin / "initdb"), "-D", str(pg_data), "-U", "postgres", "-A", "trust", "--encoding=UTF8"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [str(pg_bin / "pg_ctl"), "-D", str(pg_data), "-l", str(pg_log), "-o", f"-p {port} -k /tmp", "start"],
        check=True,
        capture_output=True,
    )
    try:
        subprocess.run(
            [str(pg_bin / "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "vmd_sec"],
            check=True,
            capture_output=True,
        )
        admin_url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/vmd_sec"
        admin_engine = create_engine(admin_url)

        # Apply Alembic head as admin/migrator
        cfg = AlembicConfig(str(backend_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_dir / "migrations"))
        os.environ["MIGRATION_DATABASE_URL"] = admin_url
        try:
            alembic_command.upgrade(cfg, "head")
        finally:
            os.environ.pop("MIGRATION_DATABASE_URL", None)

        # Provision roles & grants from deploy/neon/roles_and_grants.sql via psql + set disposable passwords
        subprocess.run(
            [
                str(pg_bin / "psql"),
                "-h", "127.0.0.1",
                "-p", str(port),
                "-U", "postgres",
                "-d", "vmd_sec",
                "-v", "ON_ERROR_STOP=1",
                "-f", str(repo_root / "deploy/neon/roles_and_grants.sql"),
            ],
            check=True,
            capture_output=True,
        )
        with admin_engine.begin() as conn:
            conn.exec_driver_sql("ALTER ROLE vmd_migrator WITH PASSWORD 'mig_pw_test'")
            conn.exec_driver_sql("ALTER ROLE vmd_app_runtime WITH PASSWORD 'app_pw_test'")
            conn.exec_driver_sql("ALTER ROLE vmd_research_readonly WITH PASSWORD 'ro_pw_test'")

        runtime_engine = create_engine(f"postgresql+psycopg://vmd_app_runtime:app_pw_test@127.0.0.1:{port}/vmd_sec")
        ro_engine = create_engine(f"postgresql+psycopg://vmd_research_readonly:ro_pw_test@127.0.0.1:{port}/vmd_sec")
        RuntimeSession = sessionmaker(bind=runtime_engine, autoflush=False, autocommit=False)

        # 1) Runtime role CAN run all legitimate MJDTA, prospective, news, and evaluation pipelines
        with RuntimeSession() as db:
            pubs = _seed_mjdta_history(db, _utc(2026, 9, 1, 4, 0), n=18)
            gen1 = pubs[-1] + timedelta(minutes=30)
            res = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1)
            assert res["status"] == "PROSPECTIVE_FORECAST_LOGGED"
            assert res["persisted"] == {"snapshots_inserted": 1, "prospective_forecasts_inserted": 8}

            # Legitimate news collection as runtime role
            art = NewsArticle(
                title="Fed cuts rates sharply, gold jumps",
                url="https://example.com/pg-role-news",
                source="Reuters",
                published_at=gen1 - timedelta(hours=1),
                ingested_at=gen1,
                first_seen_at=gen1,
            )
            d = assign_story_clusters([{"published_at": art.published_at, "title": art.title}])[0]
            art.story_cluster_id, art.cluster_key, art.cluster_version = d["story_cluster_id"], d["cluster_key"], d["cluster_version"]
            nres = persist_news_collection_to_db(
                db, run_id="pg_run_1", started_at=gen1 - timedelta(minutes=5), completed_at=gen1,
                status="SUCCESS", articles=[art], health={"queries_attempted": 5, "queries_succeeded": 5}, stats={}, label_created_at=gen1,
            )
            assert nres["labels_appended"] == 1

            # Mature h=1
            next_pub = pubs[-1] + timedelta(days=1)
            db.add(
                BullionRateObservation(
                    city_code="CHENNAI", product_id="MJDTA_GOLD_24K", source_product_id="MJDTA_GOLD",
                    price=Decimal("13550.00"), normalized_price_per_gram=Decimal("13550.00"),
                    currency="INR", rate_type="MJDTA_BENCHMARK", unit="1g",
                    source_published_at=next_pub, observed_at=next_pub + timedelta(minutes=15),
                    observation_kind="ORIGINAL", revision_number=1, validation_status="VALID",
                )
            )
            db.commit()
            mat = fe.evaluate_matured_prospective_forecasts(db)
            assert mat["prospective_evaluations_inserted"] == 4

        # 2) Runtime role MUST NOT own tables, alter schema, disable/drop triggers, modify functions, TRUNCATE, UPDATE, DELETE
        attack_sqls = [
            "ALTER TABLE forecast_runs DISABLE TRIGGER ALL",
            "DROP TRIGGER trg_forecast_runs_immutable_pg ON forecast_runs",
            "CREATE OR REPLACE FUNCTION fn_block_prospective_ledger_mutation() RETURNS trigger AS $$ BEGIN RETURN NEW; END; $$ LANGUAGE plpgsql",
            "ALTER TABLE forecast_runs ADD COLUMN backdoor text",
            "DROP TABLE forecast_runs",
            "TRUNCATE forecast_runs CASCADE",
            "TRUNCATE forecast_evaluations CASCADE",
            "TRUNCATE news_labels CASCADE",
            "UPDATE forecast_runs SET predicted_log_return = 0.99",
            "DELETE FROM forecast_runs",
            "UPDATE forecast_evaluations SET actual_log_return = 0.99",
            "DELETE FROM forecast_evaluations",
            "UPDATE news_labels SET gold_impact = 'BEARISH'",
            "DELETE FROM news_labels",
            "UPDATE bullion_rate_observations SET price = 1.0",
            "DELETE FROM bullion_rate_observations",
            "INSERT INTO alembic_version (version_num) VALUES ('fake')",
        ]
        for sql in attack_sqls:
            with pytest.raises(DB_ERRORS):
                with runtime_engine.begin() as conn:
                    conn.exec_driver_sql(sql)

        # 3) Runtime role raw-SQL forged news label WITHOUT collection_run_id gets DB-pinned available_at = NOW()
        with RuntimeSession() as db:
            art_row = db.execute(select(NewsArticleRecord)).scalar_one()
            forged_past = gen1 + timedelta(minutes=1)
            db.execute(
                text(
                    """
                    INSERT INTO news_labels
                    (article_id, story_cluster_id, collection_run_id, classification_scope, label_created_at,
                     db_recorded_at, available_at, sentiment_version, model_name, general_tone, gold_impact,
                     driver, surprise, is_price_report, feature_eligible, confidence, is_human_verified)
                    VALUES (:aid, :cid, NULL, 'CLUSTER', :past_ts, :past_ts, :past_ts,
                            'FORGED_V1', 'forged_raw', 'NEGATIVE', 'BEARISH', 'FED_POLICY', 'UNKNOWN', false, true, 'HIGH', false)
                    """
                ),
                {"aid": art_row.id, "cid": art_row.story_cluster_id, "past_ts": forged_past},
            )
            db.commit()
            forged_lbl = db.execute(select(NewsLabelRecord).where(NewsLabelRecord.model_name == "forged_raw")).scalar_one()
            # Trigger overwrote available_at & db_recorded_at to real clock_timestamp() (2026-11-12 > 2026-09-18)!
            assert forged_lbl.available_at > forged_past + timedelta(days=1)
            recs, _ = load_eligible_news_records_from_db(db, cutoff_time=gen1 + timedelta(hours=1))
            assert all(r.model_name != "forged_raw" for r in recs)

        # 4) Read-only role CAN SELECT, CANNOT INSERT/UPDATE/DELETE/TRUNCATE
        with ro_engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM forecast_runs").scalar() == 8
        for ro_attack in (
            "INSERT INTO bullion_cities (city_code, display_name, state, is_active, sort_order) VALUES ('X','X','X',true,99)",
            "UPDATE bullion_latest_rates SET latest_price = 1.0",
            "DELETE FROM forecast_runs",
        ):
            with pytest.raises(DB_ERRORS):
                with ro_engine.begin() as conn:
                    conn.exec_driver_sql(ro_attack)

        runtime_engine.dispose()
        ro_engine.dispose()
        admin_engine.dispose()
    finally:
        subprocess.run(
            [str(pg_bin / "pg_ctl"), "-D", str(pg_data), "-m", "immediate", "stop"],
            capture_output=True,
        )
        shutil.rmtree(pg_data, ignore_errors=True)
