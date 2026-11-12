from __future__ import annotations

import ast
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import re
import sys

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine
from app.models.bullion import BullionCity, BullionProduct, BullionRateObservation
from app.models.research import (
    ForecastEvaluation,
    ForecastRun,
    NewsArticleRecord,
    NewsCluster,
    NewsCollectionRun,
    NewsLabelRecord,
    ResearchFeatureSnapshot,
)
from app.services.kjpl import city_schemas as cs
from app.services.kjpl.city_parser import _build_validated_item
import app.services.kjpl.persistence as P
from app.services.ollama.classifier import (
    OllamaClassificationError,
    parse_ollama_json_response,
)
import app.services.prediction.forecast_engine as fe
from app.services.prediction.forecast_engine import (
    compute_diebold_mariano,
    evaluate_matured_prospective_forecasts,
    generate_prospective_forecast_for_frontier,
    get_latest_mjdta_research_summary,
    persist_prospective_forecast_run,
    run_backtest_study,
)
from app.services.prediction.mjdta_series import (
    MjdtaObservation,
    load_and_audit_mjdta_series,
    load_mjdta_observations_from_db,
)
from app.services.prediction.news_features import (
    compute_news_features_at_cutoff,
    load_eligible_news_records_from_db,
)
from app.services.sentiment.gold_impact import evaluate_gold_impact
from app.services.sentiment.human_review import (
    evaluate_human_review_csv,
    export_human_review_sample,
)
import app.services.sentiment.label_store as LS
from app.services.sentiment.provenance import (
    CLUSTER_VERSION,
    ProvenanceStatus,
    SENTIMENT_VERSION,
    assign_story_clusters,
    compute_story_cluster_id,
)
from app.services.sentiment.schemas import NewsArticle


def _utc(y: int, m: int, d: int, h: int = 12, minute: int = 0) -> datetime:
    return datetime(y, m, d, h, minute, 0, tzinfo=timezone.utc)


def _setup_migrated_sqlite_session(tmp_path: Path, name: str = "test_research.db", monkeypatch=None):
    """Create a genuinely Alembic-migrated (head = e8b3c1d45207) SQLite DB including triggers."""
    repo_root = Path(__file__).resolve().parents[2]
    db_file = tmp_path / name
    db_url = f"sqlite:///{db_file}"
    cfg = AlembicConfig(str(repo_root / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "backend/migrations"))

    # Configure app_engine used by migrations/env.py via temporary engine replacement
    import app.db.session as dbs
    orig_engine = dbs.engine
    orig_session = dbs.SessionLocal
    new_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    new_session = sessionmaker(bind=new_engine, autoflush=False, autocommit=False)
    dbs.engine = new_engine
    dbs.SessionLocal = new_session
    try:
        alembic_command.upgrade(cfg, "head")
    except Exception:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        new_engine.dispose()
        raise
    return new_session, new_engine, orig_engine, orig_session


def _seed_mjdta_metadata(db):
    P.seed_bullion_metadata(db, ensure_schema=False)


def test_f01_new2_new3_mjdta_publication_continuity_and_strict_isolation(tmp_path: Path, monkeypatch):
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "f01_new2_new3.db", monkeypatch)
    import app.db.session as dbs
    try:
        with Session() as db:
            _seed_mjdta_metadata(db)
            t0 = _utc(2026, 9, 1, 4, 30)
            prices = [13000, 13050, 13050, 13100, 13020, 13020, 13080, 13150, 13150, 13110,
                      13060, 13060, 13120, 13180, 13200, 13200, 13140, 13090, 13130, 13170]
            for d, p in enumerate(prices):
                t = t0 + timedelta(days=d)
                item = _build_validated_item(
                    city_code="CHENNAI", city_display_name="Chennai", product_id="MJDTA_GOLD_24K",
                    product_name="MJDTA Gold 24K", metal="GOLD", purity=0.999, weight=1.0, unit="1g",
                    rate_type="MJDTA_BENCHMARK", price=float(p), currency="INR",
                    source_product_id="MJDTA_GOLD", raw_source_name="MJDTA GOLD (Without GST)",
                )
                payload = cs.ParsedKJPLPayload(
                    observed_at=t, pipeline="MJDTA", source_updated_time="10:00 am",
                    source_updated_at=t - timedelta(minutes=30), market_status="OPEN",
                    rate_display_enabled=True, city_rates=[item], quarantined_rates=[],
                    raw_products_count=1, extraction_errors=[],
                )
                P.persist_parsed_payload(payload, session=db, source_key="KJPL_MJDTA", mirror_csv=False)

            # Repeat polling of the EXACT same day-19 publication must NOT duplicate the observation
            t_dup = t0 + timedelta(days=19)
            dup_item = _build_validated_item(
                city_code="CHENNAI", city_display_name="Chennai", product_id="MJDTA_GOLD_24K",
                product_name="MJDTA Gold 24K", metal="GOLD", purity=0.999, weight=1.0, unit="1g",
                rate_type="MJDTA_BENCHMARK", price=13170.0, currency="INR",
                source_product_id="MJDTA_GOLD", raw_source_name="MJDTA GOLD (Without GST)",
            )
            P.persist_parsed_payload(
                cs.ParsedKJPLPayload(
                    observed_at=t_dup + timedelta(minutes=15), pipeline="MJDTA", source_updated_time="10:00 am",
                    source_updated_at=t_dup - timedelta(minutes=30), market_status="OPEN",
                    rate_display_enabled=True, city_rates=[dup_item], quarantined_rates=[],
                    raw_products_count=1, extraction_errors=[],
                ),
                session=db, source_key="KJPL_MJDTA", mirror_csv=False,
            )

            # NEW-2: 20 distinct publications produce 20 VALID rows & 20 eligible series points
            obs, summary = load_mjdta_observations_from_db(db)
            elig = [o for o in obs if o.is_eligible_publication]
            assert len(elig) == 20
            assert sum(1 for o in elig if not o.is_changed) == 5

            # NEW-3: Inject plausible ALL_INDIA contamination record (source_product_id='GOLD', Rs 13431.20)
            t_contam = t0 + timedelta(days=19, hours=6)
            contam_item = _build_validated_item(
                city_code="ALL_INDIA", city_display_name="All India", product_id="MJDTA_GOLD_24K",
                product_name="MJDTA Gold 24K", metal="GOLD", purity=0.999, weight=1.0, unit="1g",
                rate_type="MJDTA_BENCHMARK", price=13431.20, currency="INR",
                source_product_id="GOLD", raw_source_name="GOLD",
            )
            P.persist_parsed_payload(
                cs.ParsedKJPLPayload(
                    observed_at=t_contam, pipeline="SNAPSHOT", source_updated_time="4:00 pm",
                    source_updated_at=t_contam, market_status="OPEN",
                    rate_display_enabled=True, city_rates=[contam_item], quarantined_rates=[],
                    raw_products_count=1, extraction_errors=[],
                ),
                session=db, source_key="KJPL_LIVE", mirror_csv=False,
            )

            obs_after, _ = load_mjdta_observations_from_db(db)
            elig_after = [o for o in obs_after if o.is_eligible_publication]
            assert len(elig_after) == 20
            assert elig_after[-1].gold_mjdta_inr_per_g == 13170.0

            # Missing source_published_at on MJDTA must quarantine rather than fabricate publication
            missing_ts_item = _build_validated_item(
                city_code="CHENNAI", city_display_name="Chennai", product_id="MJDTA_GOLD_24K",
                product_name="MJDTA Gold 24K", metal="GOLD", purity=0.999, weight=1.0, unit="1g",
                rate_type="MJDTA_BENCHMARK", price=13222.0, currency="INR",
                source_product_id="MJDTA_GOLD", raw_source_name="MJDTA GOLD (Without GST)",
            )
            q_res = P.persist_parsed_payload(
                cs.ParsedKJPLPayload(
                    observed_at=t_contam + timedelta(hours=1), pipeline="MJDTA", source_updated_time="",
                    source_updated_at=None, market_status="OPEN",
                    rate_display_enabled=True, city_rates=[missing_ts_item], quarantined_rates=[],
                    raw_products_count=1, extraction_errors=[],
                ),
                session=db, source_key="KJPL_MJDTA", mirror_csv=False,
            )
            assert q_res["records_quarantined"] == 1
            assert len([o for o in load_mjdta_observations_from_db(db)[0] if o.is_eligible_publication]) == 20
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


def test_f02_prospective_immutability_triggers_model_version_and_no_orphans(tmp_path: Path):
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "f02_triggers.db")
    import app.db.session as dbs
    try:
        with Session() as db:
            _seed_mjdta_metadata(db)
            base_dt = _utc(2026, 10, 1, 9, 30)
            for k in range(18):
                dt = base_dt + timedelta(days=k)
                db.add(
                    BullionRateObservation(
                        city_code="CHENNAI",
                        product_id="MJDTA_GOLD_24K",
                        source_product_id="MJDTA_GOLD",
                        price=Decimal(str(13000 + k * 20)),
                        currency="INR",
                        rate_type="MJDTA_BENCHMARK",
                        unit="1g",
                        normalized_price_per_gram=Decimal(str(13000 + k * 20)),
                        source_url="http://www.kjpl.in/",
                        source_published_at=dt,
                        observed_at=dt,
                        is_changed=True,
                        freshness_status="FRESH",
                        validation_status="VALID",
                    )
                )
            db.commit()

            gen1 = base_dt + timedelta(days=17, minutes=10)
            r1 = generate_prospective_forecast_for_frontier(db, generated_at=gen1)
            assert r1["status"] == "PROSPECTIVE_FORECAST_LOGGED"
            assert r1["persisted"] == {"snapshots_inserted": 1, "prospective_forecasts_inserted": 8}

            # Re-running same origin & model must insert ZERO forecasts AND ZERO orphan snapshots (NEW-7)
            r2 = generate_prospective_forecast_for_frontier(db, generated_at=gen1 + timedelta(hours=1))
            assert r2["persisted"] == {"snapshots_inserted": 0, "prospective_forecasts_inserted": 0}
            assert db.query(ResearchFeatureSnapshot).count() == 1

            # Changing model_version inserts 8 new forecasts while reusing the identical snapshot
            old_mv = fe.MODEL_VERSION
            fe.MODEL_VERSION = "RIDGE_STD_V2_AUDIT"
            try:
                r3 = generate_prospective_forecast_for_frontier(db, generated_at=gen1 + timedelta(hours=2))
                assert r3["persisted"]["prospective_forecasts_inserted"] == 8
                assert db.query(ForecastRun).filter(ForecastRun.generation_mode == "PROSPECTIVE").count() == 16
            finally:
                fe.MODEL_VERSION = old_mv

            # DB Trigger Check 1: Direct ORM UPDATE of PROSPECTIVE ForecastRun MUST raise DB error
            row = db.execute(select(ForecastRun).where(ForecastRun.generation_mode == "PROSPECTIVE").limit(1)).scalar_one()
            row.predicted_log_return = 0.0999
            with pytest.raises((IntegrityError, DBAPIError)):
                db.commit()
            db.rollback()

            # DB Trigger Check 2: Direct ORM DELETE of PROSPECTIVE ForecastRun MUST raise DB error
            db.delete(row)
            with pytest.raises((IntegrityError, DBAPIError)):
                db.commit()
            db.rollback()

            # DB Trigger Check 3: Direct ORM INSERT of hindsight PROSPECTIVE row MUST raise DB error
            old_obs = db.execute(select(BullionRateObservation).order_by(BullionRateObservation.observed_at.asc()).limit(1)).scalar_one()
            snap_id = db.execute(select(ResearchFeatureSnapshot.snapshot_id).limit(1)).scalar_one()
            db.add(
                ForecastRun(
                    forecast_id="fc_direct_hindsight",
                    protocol_version="P",
                    generation_mode="PROSPECTIVE",
                    model_version="M",
                    arm="NO_CHANGE",
                    horizon_publications=1,
                    generated_at=gen1 + timedelta(days=2),
                    cutoff_time=old_obs.observed_at,
                    origin_observation_id=old_obs.id,
                    origin_observed_at=old_obs.observed_at,
                    origin_price_inr_per_g=Decimal("13000.00"),
                    target_observation_id=None,
                    target_observed_at=None,
                    snapshot_id=snap_id,
                    feature_hash="x",
                    predicted_log_return=0.0,
                    predicted_price_inr_per_g=Decimal("13000.00"),
                    predicted_direction="FLAT",
                    up_probability=0.5,
                    status="PROSPECTIVE_ACTIVE",
                    is_immutable=True,
                )
            )
            with pytest.raises((IntegrityError, DBAPIError)):
                db.commit()
            db.rollback()

            # Mature day 18 arrives -> evaluate_matured_prospective_forecasts succeeds WITHOUT mutating ForecastRun
            dt18 = base_dt + timedelta(days=18)
            db.add(
                BullionRateObservation(
                    city_code="CHENNAI",
                    product_id="MJDTA_GOLD_24K",
                    source_product_id="MJDTA_GOLD",
                    price=Decimal("13450.00"),
                    currency="INR",
                    rate_type="MJDTA_BENCHMARK",
                    unit="1g",
                    normalized_price_per_gram=Decimal("13450.00"),
                    source_url="http://www.kjpl.in/",
                    source_published_at=dt18,
                    observed_at=dt18,
                    is_changed=True,
                    freshness_status="FRESH",
                    validation_status="VALID",
                )
            )
            db.commit()
            ev = evaluate_matured_prospective_forecasts(db)
            assert ev["prospective_evaluations_inserted"] == 8  # 4 arms * 2 model_versions for h=1
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


def test_new1_new4_new5_syndication_and_cross_run_cluster_stability(tmp_path: Path):
    Session, test_engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "new1_new5.db")
    import app.db.session as dbs
    try:
        t3 = _utc(2026, 10, 4, 6, 0)
        with Session() as db:
            # Scenario A (adv_f03): Run 1 Mint copy X -> Run 2 Reuters Y + re-sighted X
            x1 = NewsArticle(
                title="Gold price climbs on safe haven demand amid Middle East tensions",
                url="https://ex.com/x1",
                source="Mint",
                published_at=t3 - timedelta(hours=1),
                ingested_at=t3,
                first_seen_at=t3,
            )
            d1 = assign_story_clusters([{"published_at": x1.published_at, "title": x1.title}])
            x1.story_cluster_id, x1.cluster_key, x1.cluster_version = d1[0]["story_cluster_id"], d1[0]["cluster_key"], d1[0]["cluster_version"]
            LS.persist_news_collection_to_db(
                db, run_id="r1", started_at=t3, completed_at=t3, status="SUCCESS",
                articles=[x1], health={"queries_attempted": 11, "queries_succeeded": 11, "queries_failed": 0},
                stats={}, label_created_at=t3,
            )

            t4 = t3 + timedelta(hours=6)
            y1 = NewsArticle(
                title="Gold price climbs on safe haven demand amid Middle East tensions - Reuters",
                url="https://ex.com/y1",
                source="Reuters",
                published_at=t3 - timedelta(hours=3),
                ingested_at=t4,
                first_seen_at=t4,
            )
            x2 = NewsArticle(title=x1.title, url=x1.url, source="Mint", published_at=x1.published_at, ingested_at=t4, first_seen_at=t4)
            d2 = assign_story_clusters([{"published_at": y1.published_at, "title": y1.title}, {"published_at": x2.published_at, "title": x2.title}])
            y1.story_cluster_id, y1.cluster_key, y1.cluster_version = d2[0]["story_cluster_id"], d2[0]["cluster_key"], d2[0]["cluster_version"]
            x2.story_cluster_id, x2.cluster_key, x2.cluster_version = d2[1]["story_cluster_id"], d2[1]["cluster_key"], d2[1]["cluster_version"]
            assert d2[0]["story_cluster_id"] == d2[1]["story_cluster_id"]

            r2_res = LS.persist_news_collection_to_db(
                db, run_id="r2", started_at=t4, completed_at=t4, status="SUCCESS",
                articles=[y1, x2], health={"queries_attempted": 11, "queries_succeeded": 11, "queries_failed": 0},
                stats={}, label_created_at=t4,
            )
            assert r2_res["labels_appended"] == 0
            persisted_cids = {
                row.story_cluster_id
                for row in db.execute(
                    select(NewsArticleRecord).where(NewsArticleRecord.canonical_url.in_(["https://ex.com/x1", "https://ex.com/y1"]))
                ).scalars().all()
            }
            assert persisted_cids == {d1[0]["story_cluster_id"]}

            # Scenario B (adv_f03): Two differently worded members sharing one cluster over 4 repeated runs
            t5 = t3 + timedelta(days=3)
            # Audit #3: headlines naming DIFFERENT events (Fed cut vs dollar move) must no longer merge.
            from app.services.sentiment.provenance import headlines_should_merge
            assert headlines_should_merge(
                "Gold silver prices India market update Fed cuts rates",
                "Gold silver prices India market update dollar strengthens sharply",
            )[0] is False
            # Same story, differently worded members (one also mentions an opposing FX move).
            p1_title = "Gold silver prices India market update Fed cuts rates, dollar slips"
            p2_title = "Gold silver prices India market update Fed cuts rates, dollar strengthens"
            counts = []
            for k in range(4):
                tk = t5 + timedelta(hours=6 * k)
                a1 = NewsArticle(title=p1_title, url="https://ex.com/p1", source="S1", published_at=t5 - timedelta(hours=1), ingested_at=tk, first_seen_at=tk)
                a2 = NewsArticle(title=p2_title, url="https://ex.com/p2", source="S2", published_at=t5 - timedelta(minutes=30), ingested_at=tk, first_seen_at=tk)
                dd = assign_story_clusters([{"published_at": a1.published_at, "title": a1.title}, {"published_at": a2.published_at, "title": a2.title}])
                for a, rowd in zip([a1, a2], dd):
                    a.story_cluster_id, a.cluster_key, a.cluster_version = rowd["story_cluster_id"], rowd["cluster_key"], rowd["cluster_version"]
                res = LS.persist_news_collection_to_db(
                    db, run_id=f"rp_{k}", started_at=tk, completed_at=tk, status="SUCCESS",
                    articles=[a1, a2], health={"queries_attempted": 11, "queries_succeeded": 11, "queries_failed": 0},
                    stats={}, label_created_at=tk,
                )
                counts.append(res["labels_appended"])
            assert counts == [1, 0, 0, 0]

        # NEW-4: Identical headlines 90 days apart get distinct IDs
        cid_sep, _ = compute_story_cluster_id("Gold Rate Today: Check 22K gold prices in Delhi", _utc(2026, 9, 1))
        cid_nov, _ = compute_story_cluster_id("Gold Rate Today: Check 22K gold prices in Delhi", _utc(2026, 11, 30))
        assert cid_sep != cid_nov

        # F-16: Daily bulletins on 3 consecutive days MUST NOT chain indefinitely beyond 36h
        b_days = [
            {"title": "Gold Rate Today: Check 22K gold prices in Delhi", "published_at": _utc(2026, 11, 5, 8)},
            {"title": "Gold Rate Today: Check 22K gold prices in Delhi", "published_at": _utc(2026, 11, 6, 8)},
            {"title": "Gold Rate Today: Check 22K gold prices in Delhi", "published_at": _utc(2026, 11, 7, 8)},
        ]
        b_clustered = assign_story_clusters(b_days, window_hours=36.0)
        assert b_clustered[0]["story_cluster_id"] != b_clustered[2]["story_cluster_id"]
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        test_engine.dispose()


def test_f05_f07_priority6_required_headlines_and_counterexamples():
    ref = _utc(2026, 11, 10, 12, 0)
    pub = ref - timedelta(hours=1)

    r1 = evaluate_gold_impact("Gold rises as softer US inflation cools Fed rate hike bets", pub, reference_time=ref)
    assert r1["gold_impact"] == "BULLISH"
    assert r1["is_price_report"] is False

    r2 = evaluate_gold_impact("Powell: rate cuts not on the table", pub, reference_time=ref)
    assert r2["gold_impact"] == "BEARISH"
    assert r2["driver"] == "FED_POLICY"

    r3 = evaluate_gold_impact("Fed unexpectedly raises rates", pub, reference_time=ref)
    assert r3["gold_impact"] == "BEARISH"
    assert r3["surprise"] == "HAWKISH_SURPRISE"

    r4 = evaluate_gold_impact("Fed holds rates steady as expected", pub, reference_time=ref)
    assert r4["gold_impact"] == "NEUTRAL"
    assert r4["surprise"] == "AS_EXPECTED"

    r5 = evaluate_gold_impact("ECB cuts rates; Fed seen holding", pub, reference_time=ref)
    # Audit #3: foreign CB policy is not central-bank gold buying and has ambiguous net
    # transmission to INR gold -> UNKNOWN / OTHER_MACRO, never FED_POLICY or CENTRAL_BANKS.
    assert r5["gold_impact"] == "UNKNOWN"
    assert r5["driver"] == "OTHER_MACRO"

    r6 = evaluate_gold_impact("RBI hikes repo rate", pub, reference_time=ref)
    assert r6["gold_impact"] == "BEARISH"
    assert r6["driver"] == "INR"

    r7 = evaluate_gold_impact("Gold hits record high on safe-haven demand", pub, reference_time=ref)
    assert r7["gold_impact"] == "BULLISH"
    assert r7["driver"] == "GEOPOLITICS"
    assert r7["is_price_report"] is False


def test_f10_quiet_successful_day_vs_unavailable_coverage_and_f14_dm_edge_cases():
    cutoff = _utc(2026, 11, 10, 10, 0)
    # F-10: Quiet healthy run (11/11 succeeded, 0 clusters) -> coverage_ok=True, net_impact=0.0
    healthy_quiet = compute_news_features_at_cutoff(
        cutoff, [], collection_runs=[{"completed_at": cutoff - timedelta(hours=1), "status": "NO_NEW_NEWS", "queries_attempted": 11, "queries_succeeded": 11}],
    )
    assert healthy_quiet.coverage_ok is True
    assert healthy_quiet.net_impact == 0.0

    # F-10: Failed or missing run -> coverage_ok=False, net_impact=None
    failed_cov = compute_news_features_at_cutoff(
        cutoff, [], collection_runs=[{"completed_at": cutoff - timedelta(hours=1), "status": "FAILED", "queries_attempted": 11, "queries_succeeded": 0}],
    )
    assert failed_cov.coverage_ok is False
    assert failed_cov.net_impact is None

    # F-14: NaN, constant non-zero diff, and non-overlapping effective_horizon=1 checks
    nan_dm = compute_diebold_mariano([float("nan")] * 25, [0.001] * 25, horizon=1)
    assert nan_dm["status"] == "INVALID_NON_FINITE_LOSS"

    const_dm = compute_diebold_mariano([0.002] * 25, [0.001] * 25, horizon=1)
    assert const_dm["status"] == "DEGENERATE_CONSTANT_DIFFERENTIAL"

    losses_a = [0.0001 + (i % 3) * 0.00002 for i in range(25)]
    losses_b = [0.0003 + ((i + 1) % 3) * 0.00003 for i in range(25)]
    non_ov = compute_diebold_mariano(losses_a, losses_b, horizon=3, non_overlapping=True)
    assert non_ov["status"] == "COMPUTED_HLN_STUDENT_T"
    assert non_ov["effective_horizon"] == 1


def test_f11_f12_f13_f17_database_deps_and_human_review(tmp_path: Path):
    # F-11: Bad postgres fails closed in development
    with pytest.raises(RuntimeError, match="Silent SQLite fallback is prohibited"):
        build_engine(url="postgresql://invalid:invalid@127.0.0.1:59999/nonexistent", environment="development")

    # F-12: requirements-api covers runtime imports
    repo_root = Path(__file__).resolve().parents[2]
    req_text = (repo_root / "backend/requirements-api.txt").read_text(encoding="utf-8").lower()
    declared = {re.split(r"[=<>\[!~]", l.strip())[0] for l in req_text.splitlines() if l.strip() and not l.startswith("#")}
    declared_imports = set(declared) | {"bs4", "dotenv"}
    excluded = {"analyzer.py", "scheduler.py", "live_worker.py", "market_features.py"}
    needed: set[str] = set()
    for py_file in (repo_root / "backend/app").rglob("*.py"):
        if py_file.name in excluded:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    p = a.name.split(".")[0].lower()
                    if p not in sys.stdlib_module_names and p != "app":
                        needed.add(p)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                p = node.module.split(".")[0].lower()
                if p not in sys.stdlib_module_names and p != "app":
                    needed.add(p)
    assert not sorted(p for p in needed if p not in declared_imports)

    # F-17: Invalid labels detected cleanly & sampling weights applied
    rev_csv = tmp_path / "rev.csv"
    with rev_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["sample_id", "pred_gold_impact", "pred_is_price_report", "human_gold_impact", "human_is_price_report"])
        w.writeheader()
        for k in range(25):
            w.writerow({
                "sample_id": f"rev_{k}",
                "pred_gold_impact": "BULLISH",
                "pred_is_price_report": "False",
                "human_gold_impact": "bullishh" if k == 0 else "BULLISH",
                "human_is_price_report": "False",
            })
    ev = evaluate_human_review_csv(rev_csv, min_reviewed=20)
    assert ev["invalid_label_count"] == 1
    assert ev["status"] == "EVALUATED_WITH_INVALID_LABELS"
    assert "sampling_weighted_accuracy" in ev
