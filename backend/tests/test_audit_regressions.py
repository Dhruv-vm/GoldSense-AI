"""Regression tests restored from the Audit #2 test suite (Audit #3 finding A3-12).

These were dropped when test_research_forecast_and_leakage.py was consolidated.
"""
from __future__ import annotations
import ast
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import re
import pytest
from sqlalchemy import create_engine
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
from app.services.ollama.classifier import (
    OllamaClassificationError,
    parse_ollama_json_response,
)
from app.services.prediction.forecast_engine import (
    compute_diebold_mariano,
    evaluate_matured_prospective_forecasts,
    generate_prospective_forecast_for_frontier,
    get_latest_mjdta_research_summary,
    persist_prospective_forecast_run,
    persist_research_shadow_results,
    run_backtest_study,
)
from app.services.prediction.mjdta_series import (
    MjdtaObservation,
    load_and_audit_mjdta_series,
    load_mjdta_observations_from_db,
)
from app.services.prediction.news_features import (
    EligibleNewsRecord,
    compute_news_features_at_cutoff,
    load_eligible_news_records_from_db,
)
from app.services.sentiment.gold_impact import evaluate_gold_impact
from app.services.sentiment.human_review import (
    evaluate_human_review_csv,
    export_human_review_sample,
)
from app.services.sentiment.label_store import (
    compute_label_hash,
    persist_news_collection_to_db,
)
from app.services.sentiment.provenance import (
    CLUSTER_VERSION,
    ProvenanceStatus,
    SENTIMENT_VERSION,
    assign_story_clusters,
    compute_story_cluster_id,
    is_synthetic_fixture_url,
    normalize_language,
)
from app.services.sentiment.schemas import NewsArticle


def _utc(y: int, m: int, d: int, h: int = 12, minute: int = 0) -> datetime:
    return datetime(y, m, d, h, minute, 0, tzinfo=timezone.utc)


def _setup_sqlite_session(tmp_path: Path, name: str = "test_research.db"):
    db_file = tmp_path / name
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _seed_mjdta_metadata(db):
    db.add(BullionCity(city_code="CHENNAI", display_name="Chennai", state="Tamil Nadu", is_active=True, sort_order=1))
    db.add(
        BullionProduct(
            product_id="MJDTA_GOLD_24K",
            product_name="MJDTA Gold 24K Benchmark (Excl. GST)",
            metal="GOLD",
            purity=Decimal("0.9990"),
            weight=Decimal("1.0000"),
            unit="1g",
            rate_type="MJDTA_BENCHMARK",
            source_product_id="MJDTA_GOLD",
            is_active=True,
        )
    )
    db.commit()


def test_f01_mjdta_db_continuity_sees_new_observations(tmp_path: Path):
    Session = _setup_sqlite_session(tmp_path, "f01.db")
    with Session() as db:
        _seed_mjdta_metadata(db)
        base_dt = _utc(2026, 10, 1, 9, 30)
        for k in range(12):
            dt = base_dt + timedelta(days=k)
            db.add(
                BullionRateObservation(
                    city_code="CHENNAI",
                    product_id="MJDTA_GOLD_24K",
                    source_product_id="MJDTA_GOLD",
                    price=Decimal(str(13100 + k * 15)),
                    currency="INR",
                    rate_type="MJDTA_BENCHMARK",
                    unit="1g",
                    normalized_price_per_gram=Decimal(str(13100 + k * 15)),
                    source_url="http://www.kjpl.in/",
                    source_published_at=dt,
                    observed_at=dt + timedelta(minutes=5),
                    is_changed=True,
                    freshness_status="FRESH",
                    validation_status="VALID",
                )
            )
        db.commit()

        obs_before, summary_before = load_mjdta_observations_from_db(db)
        assert summary_before["source_backend"] == "database"
        assert summary_before["eligible_publications"] == 12

        # Persist one new observation in DB (simulating KJPL collector)
        new_dt = base_dt + timedelta(days=12)
        db.add(
            BullionRateObservation(
                city_code="CHENNAI",
                product_id="MJDTA_GOLD_24K",
                source_product_id="MJDTA_GOLD",
                price=Decimal("13425.00"),
                currency="INR",
                rate_type="MJDTA_BENCHMARK",
                unit="1g",
                normalized_price_per_gram=Decimal("13425.00"),
                source_url="http://www.kjpl.in/",
                source_published_at=new_dt,
                observed_at=new_dt + timedelta(minutes=5),
                is_changed=True,
                freshness_status="FRESH",
                validation_status="VALID",
            )
        )
        db.commit()

        obs_after, summary_after = load_mjdta_observations_from_db(db)
        assert len(obs_after) == 13
        assert obs_after[-1].gold_mjdta_inr_per_g == 13425.0
        research = get_latest_mjdta_research_summary(db=db)
        assert research["eligible_publications"] == 13
        assert research["mjdta_audit"]["source_backend"] == "database"


def test_f02_prospective_rejects_hindsight_and_separates_from_backtest(tmp_path: Path):
    Session = _setup_sqlite_session(tmp_path, "f02.db")
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

        # Run prospective generation strictly on the frontier (day 17, before day 18 exists)
        frontier_gen = base_dt + timedelta(days=17, minutes=10)
        res = generate_prospective_forecast_for_frontier(db, generated_at=frontier_gen)
        assert res["status"] == "PROSPECTIVE_FORECAST_LOGGED"
        assert db.query(ForecastRun).filter(ForecastRun.generation_mode == "PROSPECTIVE").count() == 8
        assert db.query(ForecastEvaluation).filter(ForecastEvaluation.generation_mode == "PROSPECTIVE").count() == 0

        # Adversarial hindsight test: try persisting a PROSPECTIVE forecast for day 10 (when days 11..17 already exist!)
        past_origin = (base_dt + timedelta(days=10)).isoformat()
        with pytest.raises(ValueError, match="Hindsight error"):
            from app.services.prediction.forecast_engine import ShadowForecastRecord

            persist_prospective_forecast_run(
                db,
                snapshot={
                    "snapshot_id": "snap_fake_hindsight",
                    "generation_mode": "PROSPECTIVE",
                    "cutoff_time": past_origin,
                    "label_cutoff_time": past_origin,
                    "target_product": "MJDTA_GOLD_24K",
                    "origin_observation_id": 11,
                    "origin_observed_at": past_origin,
                    "origin_gold_price_inr_per_g": 13200.0,
                    "feature_version": "NEWS_FEATURES_V2",
                    "cluster_version": CLUSTER_VERSION,
                    "sentiment_version": SENTIMENT_VERSION,
                    "feature_hash": "abc",
                    "n_clusters_relevant": 0,
                    "net_impact": None,
                    "unknown_share": None,
                    "coverage_ok": False,
                    "features_json": {},
                },
                forecasts=[
                    ShadowForecastRecord(
                        forecast_id="fc_fake_hindsight",
                        protocol_version="EXPERIMENT_PROTOCOL_V1",
                        generation_mode="PROSPECTIVE",
                        model_version="RIDGE_STD_V1",
                        arm="NO_CHANGE",
                        horizon_publications=1,
                        generated_at=past_origin,
                        cutoff_time=past_origin,
                        origin_observation_id=11,
                        origin_observed_at=past_origin,
                        origin_price_inr_per_g=13200.0,
                        target_observation_id=None,
                        target_observed_at=None,
                        snapshot_id="snap_fake_hindsight",
                        feature_hash="abc",
                        predicted_log_return=0.0,
                        predicted_price_inr_per_g=13200.0,
                        predicted_direction="FLAT",
                        up_probability=0.5,
                        status="PROSPECTIVE_ACTIVE",
                        coverage_ok=False,
                    )
                ],
            )

        # Now day 18 genuinely arrives in DB -> delayed evaluation scores ONLY the matured h=1 PROSPECTIVE runs!
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
        ev_stats = evaluate_matured_prospective_forecasts(db)
        assert ev_stats["prospective_evaluations_inserted"] == 4  # 4 arms for h=1 matured


def test_f03_stored_immutable_labels_prevent_retroactive_sign_flip(tmp_path: Path):
    """
    Reproduce Claude's +0.0851 -> -0.0851 sign-flip regression:
    Historical cutoff T must NEVER mutate when a classifier update writes new labels at T + 2h.
    """
    Session = _setup_sqlite_session(tmp_path, "f03.db")
    cutoff_t = _utc(2026, 11, 10, 10, 0)
    with Session() as db:
        articles = [
            NewsArticle(
                title="Fed signals rate cuts as yields tumble",
                url="https://example.com/fed-1",
                published_at=cutoff_t - timedelta(hours=3),
                first_seen_at=cutoff_t - timedelta(hours=2),
                ingested_at=cutoff_t - timedelta(hours=2),
                source="Reuters",
                language="en",
            ),
            NewsArticle(
                title="Central bank gold buying boosts reserves",
                url="https://example.com/cb-2",
                published_at=cutoff_t - timedelta(hours=3),
                first_seen_at=cutoff_t - timedelta(hours=2),
                ingested_at=cutoff_t - timedelta(hours=2),
                source="Bloomberg",
                language="en",
            ),
        ]
        persist_news_collection_to_db(
            db,
            run_id="run_before_t",
            started_at=cutoff_t - timedelta(hours=2, minutes=5),
            completed_at=cutoff_t - timedelta(hours=2),
            status="SUCCESS",
            articles=articles,
            health={"queries_attempted": 5, "queries_succeeded": 5, "queries_failed": 0},
            stats={"new_archive_count": 2, "live_count": 2},
            label_created_at=cutoff_t - timedelta(hours=1),
        )

        recs_before, runs_before = load_eligible_news_records_from_db(db, cutoff_time=cutoff_t)
        feat_before = compute_news_features_at_cutoff(cutoff_t, recs_before, runs_before)
        assert feat_before.coverage_ok is True
        assert feat_before.net_impact == 1.0  # Both clusters BULLISH as of cutoff_t

        # Now at T + 2h, append flipped BEARISH labels simulating a classifier revision
        later_ts = cutoff_t + timedelta(hours=2)
        for art in db.query(NewsArticleRecord).all():
            db.add(
                NewsLabelRecord(
                    article_id=art.id,
                    story_cluster_id=art.story_cluster_id,
                    label_created_at=later_ts,
                    available_at=later_ts,
                    sentiment_version="GOLD_SENTIMENT_V3_REVISED",
                    model_name="flipped_classifier_v3",
                    general_tone="NEGATIVE",
                    gold_impact="BEARISH",
                    driver="FED_POLICY",
                    surprise="UNKNOWN",
                    is_price_report=False,
                    feature_eligible=True,
                    label_hash=compute_label_hash(
                        story_cluster_id=art.story_cluster_id,
                        sentiment_version="GOLD_SENTIMENT_V3_REVISED",
                        model_name="flipped_classifier_v3",
                        gold_impact="BEARISH",
                        driver="FED_POLICY",
                        is_price_report=False,
                    ),
                    confidence="HIGH",
                    evidence_rationale="Simulated post-cutoff classifier flip",
                )
            )
        db.commit()

        # Re-evaluating strictly as of cutoff_t MUST STILL yield +1.0 (zero retroactive flip!)
        recs_replay, runs_replay = load_eligible_news_records_from_db(db, cutoff_time=cutoff_t)
        feat_replay = compute_news_features_at_cutoff(cutoff_t, recs_replay, runs_replay)
        assert feat_replay.net_impact == feat_before.net_impact == 1.0
        assert feat_replay.feature_hash == feat_before.feature_hash

        # Evaluating strictly AFTER later_ts sees the newer label version (-1.0)
        recs_later, runs_later = load_eligible_news_records_from_db(db, cutoff_time=later_ts + timedelta(minutes=1))
        feat_later = compute_news_features_at_cutoff(later_ts + timedelta(minutes=1), recs_later, runs_later)
        assert feat_later.net_impact == -1.0


def test_f05_f06_f07_classifier_logic_and_unknown_handling():
    ref = _utc(2026, 11, 10, 12, 0)

    # F-05: Negated hike / dovish pause must NOT trigger BEARISH_FED_PATTERNS
    dovish = evaluate_gold_impact("Fed pauses rate hikes and signals easing ahead", ref - timedelta(hours=1), reference_time=ref)
    assert dovish["gold_impact"] == "BULLISH"
    assert dovish["driver"] == "FED_POLICY"

    # F-05: Central bank halting/selling reserves is BEARISH (not blindly BULLISH)
    cb_sell = evaluate_gold_impact("Central bank halts gold purchases as reserves drop", ref - timedelta(hours=1), reference_time=ref)
    assert cb_sell["gold_impact"] == "BEARISH"
    assert cb_sell["driver"] == "CENTRAL_BANKS"

    # F-06: Insufficient preview cues stay UNKNOWN (not forced into MIXED)
    preview = evaluate_gold_impact("Markets brace for Fed meeting next week", ref - timedelta(hours=1), reference_time=ref)
    assert preview["gold_impact"] == "UNKNOWN"
    assert preview["driver"] == "FED_POLICY"

    # F-06: Genuinely conflicting directional forces -> MIXED
    conflict = evaluate_gold_impact("Dollar weakens sharply even as rising Treasury yields pressure gold", ref - timedelta(hours=1), reference_time=ref)
    assert conflict["gold_impact"] == "MIXED"

    # F-07: Daily price report matched FIRST before momentum buzzwords
    price_rep = evaluate_gold_impact(
        "Gold price today: Yellow metal hits record high in Mumbai; check 22K and 24K rates",
        ref - timedelta(hours=1),
        reference_time=ref,
    )
    assert price_rep["is_price_report"] is True
    assert price_rep["driver"] == "GOLD_PRICE_REPORT"
    assert price_rep["gold_impact"] == "NEUTRAL"


def test_f08_f09_f10_f14_statistical_arms_missing_news_and_hln_dm():
    base_time = _utc(2026, 10, 1, 9, 30)
    obs = [
        MjdtaObservation(
            sequence_index=k + 1,
            observed_at_utc=base_time + timedelta(days=k),
            available_at_utc=base_time + timedelta(days=k),
            inferred_published_at_utc=base_time + timedelta(days=k),
            has_explicit_source_date=True,
            published_time_raw="",
            gold_mjdta_inr_per_g=13000.0 + k * 25.0 + ((-1) ** k) * 30.0,
            silver_mjdta_inr_per_g=210.0,
            source="KJPL",
            timestamp_status="VALID_EXPLICIT_TIMESTAMP",
            is_eligible_publication=True,
            exclusion_reason="",
        )
        for k in range(25)
    ]

    # F-10: Failed collection run with zero news -> coverage_ok=False, net_impact=None
    res_no_news = run_backtest_study(obs, [], collection_runs=[])
    assert res_no_news["latest_snapshot"]["coverage_ok"] is False
    assert res_no_news["latest_snapshot"]["net_impact"] is None
    assert res_no_news["latest_snapshot"]["unknown_share"] is None

    # F-08 / F-09: NEWS_ONLY & HYBRID must emit UNAVAILABLE (None), NOT heuristic priors or fake 0.0
    news_fc = [f for f in res_no_news["latest_forecasts"] if f["arm"] == "NEWS_ONLY"][0]
    assert news_fc["predicted_log_return"] is None
    assert news_fc["status"] == "UNAVAILABLE_NO_NEWS_COVERAGE"
    assert res_no_news["metrics_by_horizon"]["h1"]["paired_comparable_count"] == 0

    # F-14: HLN Student-t DM checks
    identical_dm = compute_diebold_mariano([0.001] * 25, [0.001] * 25, horizon=1)
    assert identical_dm["status"] == "DEGENERATE_IDENTICAL_PREDICTIONS"

    small_dm = compute_diebold_mariano([0.001, 0.002], [0.002, 0.003], horizon=1)
    assert small_dm["status"] == "INSUFFICIENT_SAMPLE"

    losses_a = [0.0001 + (i % 3) * 0.00002 for i in range(25)]
    losses_b = [0.0003 + ((i + 1) % 3) * 0.00003 for i in range(25)]
    hln_dm = compute_diebold_mariano(losses_a, losses_b, horizon=1)
    assert hln_dm["status"] == "COMPUTED_HLN_STUDENT_T"
    assert hln_dm["df"] == 24
    assert hln_dm["dm_stat"] is not None and hln_dm["dm_stat"] < 0


def test_f11_postgres_failure_never_falls_back_to_sqlite():
    with pytest.raises(RuntimeError, match="Silent SQLite fallback is prohibited"):
        build_engine(
            url="postgresql://invalid:invalid@127.0.0.1:59999/nonexistent",
            environment="development",
        )


def test_f12_requirements_api_covers_fastapi_runtime_imports():
    repo_root = Path(__file__).resolve().parents[2]
    req_text = (repo_root / "backend/requirements-api.txt").read_text(encoding="utf-8").lower()
    declared = {
        re.split(r"[=<>\[!~]", line.strip())[0]
        for line in req_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    declared_imports = set(declared)
    if "beautifulsoup4" in declared:
        declared_imports.add("bs4")
    if "python-dotenv" in declared:
        declared_imports.add("dotenv")
    if "psycopg" in declared:
        declared_imports.add("psycopg")

    # Parse backend/app modules reachable outside optional offline workers/ML
    excluded_files = {"analyzer.py", "scheduler.py", "live_worker.py", "market_features.py"}
    needed: set[str] = set()
    import sys

    for py_file in (repo_root / "backend/app").rglob("*.py"):
        if py_file.name in excluded_files:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        # Only inspect top-level module imports (inside function lazy imports stay optional)
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = alias.name.split(".")[0].lower()
                    if pkg not in sys.stdlib_module_names and pkg != "app":
                        needed.add(pkg)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                pkg = node.module.split(".")[0].lower()
                if pkg not in sys.stdlib_module_names and pkg != "app":
                    needed.add(pkg)

    missing = sorted(pkg for pkg in needed if pkg not in declared_imports)
    assert not missing, f"Missing runtime packages from backend/requirements-api.txt: {missing}"


def test_f13_f17_human_review_protects_annotations_and_blinds_sheet(tmp_path: Path):
    audited = tmp_path / "audited.csv"
    with audited.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["published_at", "first_seen_at", "provenance_status", "source", "language", "story_cluster_id", "title", "url"],
        )
        w.writeheader()
        for k in range(30):
            w.writerow(
                {
                    "published_at": _utc(2026, 11, 1 + (k % 10), 10).isoformat(),
                    "first_seen_at": _utc(2026, 11, 1 + (k % 10), 11).isoformat(),
                    "provenance_status": ProvenanceStatus.VERIFIED_SOURCE.value,
                    "source": f"source_{k % 6}",
                    "language": "en",
                    "story_cluster_id": f"clu_{k}",
                    "title": f"Fed rate decision headline sample {k}",
                    "url": f"https://example.com/{k}",
                }
            )

    review_csv = tmp_path / "human_review_sample.csv"
    ref_csv = tmp_path / "human_review_reference.csv"
    export_human_review_sample(audited, review_csv, sample_size=25, reference_output_path=ref_csv)

    with review_csv.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # F-17: Blinded sheet omits model pred_* columns
        assert "pred_gold_impact" not in (reader.fieldnames or [])
        rows = list(reader)

    # Annotate row 0 and write back
    rows[0]["human_gold_impact"] = "UNKNOWN"
    with review_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # F-13: Overwrite attempt MUST FAIL even with overwrite=True when human annotations exist
    with pytest.raises(FileExistsError, match="preserve human annotations"):
        export_human_review_sample(audited, review_csv, sample_size=25, reference_output_path=ref_csv, overwrite=True)


def test_f16_sliding_clustering_survives_utc_midnight_boundary():
    a1 = {"title": "Fed Holds Rates Steady Amid Inflation Risk - Reuters", "published_at": _utc(2026, 11, 9, 23, 55)}
    a2 = {"title": "Fed Holds Rates Steady Amid Inflation Risk | Bloomberg", "published_at": _utc(2026, 11, 10, 0, 5)}
    clustered = assign_story_clusters([a1, a2], window_hours=36.0)
    assert clustered[0]["story_cluster_id"] == clustered[1]["story_cluster_id"]


def test_ollama_strict_json_validation():
    parsed = parse_ollama_json_response(
        '<think>Check Fed</think>{"general_tone":"NEUTRAL","gold_impact":"BULLISH","driver":"FED_POLICY","surprise":"DOVISH_SURPRISE","is_price_report":false,"confidence":"HIGH","evidence_rationale":"Cut supports gold."}'
    )
    assert parsed.gold_impact.value == "BULLISH"
    with pytest.raises(OllamaClassificationError):
        parse_ollama_json_response("bad json")

