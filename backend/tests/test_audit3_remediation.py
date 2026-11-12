"""Regression tests for the Audit #3 (2026-11-11) remediation.

Each test names the finding it pins: A3-1..A3-11 and the F-05 / F-07 / F-10 residuals.
"""
from __future__ import annotations

import importlib
import linecache
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.services.kjpl.city_schemas import ParsedCityRate, ParsedKJPLPayload
from app.services.kjpl.parser import resolve_clock_only_kjpl_time
from app.services.sentiment.gold_impact import evaluate_gold_impact
from app.services.sentiment.provenance import assign_story_clusters, headlines_should_merge

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
TRIGGER_ERRORS = (IntegrityError, OperationalError, DatabaseError)


# ---------------------------------------------------------------------------
# A3-5: clock-only KJPL timestamps
# ---------------------------------------------------------------------------
def test_a3_5_clock_only_time_after_midnight_rolls_back_one_day():
    now = datetime(2026, 11, 12, 0, 10, tzinfo=IST)
    resolved = resolve_clock_only_kjpl_time("11:50 pm", now)
    assert resolved == datetime(2026, 11, 11, 23, 50, tzinfo=IST)


def test_a3_5_clock_only_time_earlier_today_stays_today():
    now = datetime(2026, 11, 11, 15, 0, tzinfo=IST)
    assert resolve_clock_only_kjpl_time("09:37 am", now) == datetime(2026, 11, 11, 9, 37, tzinfo=IST)
    # A3-FINAL-4: a clock-only time ahead of collection time is never stamped in the future or guessed as yesterday
    assert resolve_clock_only_kjpl_time("03:03 pm", now) is None


def test_a3_5_clock_only_rejects_impossible_clock():
    now = datetime(2026, 11, 11, 15, 0, tzinfo=IST)
    assert resolve_clock_only_kjpl_time("13:10 pm", now) is None


# ---------------------------------------------------------------------------
# A3-5 / A3-10 / A3-11: MJDTA persistence + loader
# ---------------------------------------------------------------------------
def _mjdta_rate(price: float) -> ParsedCityRate:
    return ParsedCityRate(
        city_code="CHENNAI",
        city_display_name="Chennai",
        product_id="MJDTA_GOLD_24K",
        product_name="MJDTA Gold 24K Pure (Chennai Benchmark)",
        metal="GOLD",
        purity=0.999,
        weight=1.0,
        unit="1g",
        rate_type="MJDTA_BENCHMARK",
        price=price,
        normalized_price_per_gram=price,
        currency="INR",
        source_product_id="MJDTA_GOLD",
        raw_source_name="MJDTA GOLD (Without GST)",
    )


def _payload(price: float, pub_ist: datetime, precision: str) -> ParsedKJPLPayload:
    return ParsedKJPLPayload(
        observed_at=datetime.now(IST),
        pipeline="KJPL_MJDTA",
        source_updated_time=pub_ist.strftime("%I:%M %p"),
        source_updated_at=pub_ist,
        source_timestamp_precision=precision,
        city_rates=[_mjdta_rate(price)],
    )


@pytest.fixture()
def kjpl_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'kjpl.db'}")
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as s:
        yield s
    engine.dispose()


def _valid_mjdta_rows(session):
    from app.models.bullion import BullionRateObservation

    return session.execute(
        select(BullionRateObservation).where(
            BullionRateObservation.product_id == "MJDTA_GOLD_24K",
            BullionRateObservation.validation_status == "VALID",
        )
    ).scalars().all()


def test_a3_5_future_mjdta_publication_is_quarantined(kjpl_session):
    from app.services.kjpl.persistence import persist_parsed_payload

    future = (datetime.now(IST) + timedelta(hours=2)).replace(second=0, microsecond=0)
    res = persist_parsed_payload(_payload(13100.0, future, "FULL"), session=kjpl_session, mirror_csv=False)
    assert res["records_quarantined"] == 1
    assert "Future source_published_at" in res["item_logs"][0]["persistence_result"]
    assert _valid_mjdta_rows(kjpl_session) == []


def test_a3_5_clock_only_carryover_is_not_a_new_publication(kjpl_session):
    from app.services.kjpl.persistence import persist_parsed_payload

    today_pub = (datetime.now(IST) - timedelta(hours=1)).replace(second=0, microsecond=0)
    yesterday_pub = today_pub - timedelta(days=1)

    persist_parsed_payload(_payload(13100.0, yesterday_pub, "FULL"), session=kjpl_session, mirror_csv=False)
    assert len(_valid_mjdta_rows(kjpl_session)) == 1

    # Sunday/holiday: page still shows yesterday's HH:MM, date inferred as today, same price.
    res = persist_parsed_payload(_payload(13100.0, today_pub, "CLOCK_ONLY"), session=kjpl_session, mirror_csv=False)
    assert len(_valid_mjdta_rows(kjpl_session)) == 1
    assert res["item_logs"][-1]["persistence_result"] == "SKIPPED_CLOCK_ONLY_CARRYOVER"

    # A FULL timestamp at the same clock time on a new day IS a genuine publication.
    persist_parsed_payload(_payload(13100.0, today_pub, "FULL"), session=kjpl_session, mirror_csv=False)
    assert len(_valid_mjdta_rows(kjpl_session)) == 2


def test_a3_10_same_publication_correction_supersedes_in_loader(kjpl_session):
    from app.services.kjpl.persistence import persist_parsed_payload
    from app.services.prediction.mjdta_series import load_mjdta_observations_from_db

    pub = (datetime.now(IST) - timedelta(hours=3)).replace(second=0, microsecond=0)
    persist_parsed_payload(_payload(13100.0, pub, "FULL"), session=kjpl_session, mirror_csv=False)
    persist_parsed_payload(_payload(13120.0, pub, "FULL"), session=kjpl_session, mirror_csv=False)  # correction
    assert len(_valid_mjdta_rows(kjpl_session)) == 2  # raw history keeps both rows

    obs, summary = load_mjdta_observations_from_db(kjpl_session)
    assert summary["superseded_same_publication_rows"] == 1
    prices = [o.gold_mjdta_inr_per_g for o in obs]
    assert 13120.0 in prices and 13100.0 not in prices


def test_a3_11_loader_filters_observation_unit_and_rate_type(kjpl_session):
    from app.models.bullion import BullionRateObservation
    from app.services.kjpl.persistence import persist_parsed_payload
    from app.services.prediction.mjdta_series import load_mjdta_observations_from_db

    pub = (datetime.now(IST) - timedelta(hours=5)).replace(second=0, microsecond=0)
    persist_parsed_payload(_payload(13100.0, pub, "FULL"), session=kjpl_session, mirror_csv=False)
    _, before = load_mjdta_observations_from_db(kjpl_session)

    for unit, rate_type in (("10g", "MJDTA_BENCHMARK"), ("1g", "RETAIL")):
        kjpl_session.add(
            BullionRateObservation(
                city_code="CHENNAI", product_id="MJDTA_GOLD_24K", source_product_id="MJDTA_GOLD",
                price=Decimal("131000"), currency="INR", rate_type=rate_type, unit=unit,
                normalized_price_per_gram=Decimal("131000"), source_url="x",
                source_published_at=(pub + timedelta(hours=1)).astimezone(UTC),
                observed_at=datetime.now(UTC), is_changed=True, freshness_status="FRESH",
                validation_status="VALID",
            )
        )
    kjpl_session.commit()
    _, after = load_mjdta_observations_from_db(kjpl_session)
    assert after["eligible_publications"] == before["eligible_publications"]


# ---------------------------------------------------------------------------
# F-05 / F-07 / A3-9 classifier residuals
# ---------------------------------------------------------------------------
_T = datetime(2026, 11, 11, tzinfo=UTC)


@pytest.mark.parametrize(
    "title,impact,driver",
    [
        ("Fed cuts rates by 25 bps as widely expected", "NEUTRAL", "FED_POLICY"),
        ("Fed hikes rates as expected", "NEUTRAL", "FED_POLICY"),
        ("Fed officials push back against rate cut expectations", "BEARISH", "FED_POLICY"),
        ("Fed officials push back against rate-cut bets", "BEARISH", "FED_POLICY"),
        ("Fed surprises markets with 50 bps cut", "BULLISH", "FED_POLICY"),
        ("Fed holds rates, signals no cuts this year", "BEARISH", "FED_POLICY"),
        ("Powell says Fed will not cut rates soon", "BEARISH", "FED_POLICY"),
        ("ECB cuts interest rates", "UNKNOWN", "OTHER_MACRO"),
        ("BoJ raises rates for first time in 17 years", "UNKNOWN", "OTHER_MACRO"),
        ("Gold price today in India: RBI hikes repo rate by 25 bps", "BEARISH", "INR"),
        ("Gold price today in India: rupee hits record low", "BULLISH", "INR"),
        ("Gold rate today: check 22k and 24k prices in Chennai, Mumbai", "NEUTRAL", "GOLD_PRICE_REPORT"),
        ("Fed unexpectedly cuts rates", "BULLISH", "FED_POLICY"),
        ("Traders pare back Fed rate hike bets", "BULLISH", "FED_POLICY"),
    ],
)
def test_f05_f07_a3_9_classifier_residuals(title, impact, driver):
    r = evaluate_gold_impact(title, _T, reference_time=_T)
    assert (r["gold_impact"], r["driver"]) == (impact, driver)


def test_f05_gold_fails_to_rally_is_not_bullish():
    r = evaluate_gold_impact("Gold fails to rally despite weak dollar", _T, reference_time=_T)
    assert r["gold_impact"] != "BULLISH"


# ---------------------------------------------------------------------------
# Cluster merge guard + deterministic best match
# ---------------------------------------------------------------------------
def test_clusters_do_not_merge_distinct_events():
    assert not headlines_should_merge("Gold steadies ahead of US CPI data", "Gold steadies ahead of US PPI data")[0]
    assert not headlines_should_merge(
        "Gold rate today in Chennai: 22 carat at Rs 7,250", "Gold rate today in Chennai: 22 carat at Rs 7,300"
    )[0]
    assert not headlines_should_merge("Gold rises as dollar weakens", "Gold falls as dollar weakens")[0]
    assert headlines_should_merge("Gold rises as dollar weakens - Reuters", "Gold rises as dollar weakens - Mint")[0]
    assert headlines_should_merge(
        "Gold rises as dollar weakens after Fed", "Gold climbs as dollar weakens after Fed"
    )[0]


def test_in_batch_clustering_splits_cpi_and_ppi():
    t = datetime(2026, 11, 10, 8, tzinfo=UTC)
    rows = assign_story_clusters([
        {"title": "Gold steadies ahead of US CPI data", "published_at": t},
        {"title": "Gold steadies ahead of US PPI data", "published_at": t + timedelta(hours=1)},
    ])
    assert rows[0]["story_cluster_id"] != rows[1]["story_cluster_id"]


# ---------------------------------------------------------------------------
# A3-6: classifier digest covers module-level rule tables, not bytecode
# ---------------------------------------------------------------------------
def test_a3_6_digest_changes_when_module_rule_table_changes(tmp_path, monkeypatch):
    from app.services.sentiment.label_store import _classifier_implementation_digest

    mod_file = tmp_path / "fake_rules_mod.py"
    body = "RULES = [{rule!r}]\n\ndef classify(title):\n    return title in RULES\n"
    mod_file.write_text(body.format(rule="fed cuts"))
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = importlib.import_module("fake_rules_mod")
    d1 = _classifier_implementation_digest(mod.classify)
    assert d1 == _classifier_implementation_digest(mod.classify)  # deterministic

    mod_file.write_text(body.format(rule="fed hikes"))  # only the module-level table changes
    linecache.checkcache(str(mod_file))
    mod = importlib.reload(mod)
    d2 = _classifier_implementation_digest(mod.classify)
    sys.modules.pop("fake_rules_mod", None)
    assert d1 != d2


# ---------------------------------------------------------------------------
# F-10 residual: latest run in window decides coverage
# ---------------------------------------------------------------------------
def test_f10_newer_failed_run_overrides_older_success():
    from app.services.prediction.news_features import compute_news_features_at_cutoff

    cutoff = datetime(2026, 11, 10, 10, tzinfo=UTC)
    ok = {"run_id": "a", "completed_at": (cutoff - timedelta(hours=8)).isoformat(), "status": "SUCCESS",
          "queries_attempted": 10, "queries_succeeded": 10}
    failed = {"run_id": "b", "completed_at": (cutoff - timedelta(hours=1)).isoformat(), "status": "FAILED",
              "queries_attempted": 10, "queries_succeeded": 0}
    feats = compute_news_features_at_cutoff(cutoff, [], collection_runs=[ok, failed])
    assert feats.coverage_ok is False
    assert feats.net_impact is None

    feats2 = compute_news_features_at_cutoff(cutoff, [], collection_runs=[failed | {"completed_at": ok["completed_at"]},
                                                                           ok | {"completed_at": failed["completed_at"]}])
    assert feats2.coverage_ok is True


# ---------------------------------------------------------------------------
# DB triggers (A3-1..A3-4) on an Alembic-migrated SQLite DB
# ---------------------------------------------------------------------------
@pytest.fixture()
def migrated(tmp_path, monkeypatch):
    from tests.test_research_forecast_and_leakage import _setup_migrated_sqlite_session
    import app.db.session as dbs

    Session, engine, orig_engine, orig_session = _setup_migrated_sqlite_session(tmp_path, "trg.db", monkeypatch)
    try:
        yield engine
    finally:
        dbs.engine = orig_engine
        dbs.SessionLocal = orig_session
        engine.dispose()


def _cols(conn, table):
    return [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]


def _insert_min_row(conn, table, overrides):
    """Insert a row filling NOT NULL columns with type-appropriate dummies."""
    info = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    vals = {}
    for _cid, name, ctype, notnull, default, pk in info:
        if pk or name in overrides:
            continue
        if notnull and default is None:
            t = (ctype or "").upper()
            if any(k in t for k in ("INT", "BOOL")):
                vals[name] = 0
            elif any(k in t for k in ("NUM", "DEC", "FLOAT", "REAL", "DOUBLE")):
                vals[name] = 1.0
            elif any(k in t for k in ("DATE", "TIME")):
                vals[name] = "2026-11-10 10:00:00"
            elif "JSON" in t:
                vals[name] = "{}"
            else:
                vals[name] = f"x_{name}_{uuid.uuid4().hex[:8]}"
    vals.update(overrides)
    cols = ", ".join(vals)
    params = ", ".join(f":{k}" for k in vals)
    res = conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), vals)
    return res.lastrowid


def test_a3_1_backtest_row_cannot_be_promoted_to_prospective(migrated):
    with migrated.begin() as conn:
        rid = _insert_min_row(conn, "forecast_runs", {"generation_mode": "BACKTEST"})
    with pytest.raises(TRIGGER_ERRORS):
        with migrated.begin() as conn:
            conn.execute(text("UPDATE forecast_runs SET generation_mode='PROSPECTIVE' WHERE id=:i"), {"i": rid})


def test_a3_2_forecast_evaluations_are_immutable(migrated):
    from app.services.kjpl.persistence import seed_bullion_metadata
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=migrated)
    with Session() as s:
        seed_bullion_metadata(s, ensure_schema=False)

    with migrated.begin() as conn:
        orig_obs_id = _insert_min_row(
            conn,
            "bullion_rate_observations",
            {
                "city_code": "CHENNAI",
                "product_id": "MJDTA_GOLD_24K",
                "source_product_id": "MJDTA_GOLD",
                "price": 13000.0,
                "normalized_price_per_gram": 13000.0,
                "unit": "1g",
                "rate_type": "MJDTA_BENCHMARK",
                "validation_status": "VALID",
                "observation_kind": "ORIGINAL",
                "revision_number": 1,
                "source_published_at": "2026-11-01 04:00:00",
                "observed_at": "2026-11-01 04:05:00",
            },
        )
        snap_id = f"snap_{uuid.uuid4().hex[:8]}"
        _insert_min_row(
            conn,
            "research_feature_snapshots",
            {
                "snapshot_id": snap_id,
                "generation_mode": "PROSPECTIVE",
                "origin_observation_id": orig_obs_id,
                "origin_observed_at": "2026-11-01 04:05:00",
            },
        )
        fc_prosp_id = f"fc_{uuid.uuid4().hex[:8]}"
        _insert_min_row(
            conn,
            "forecast_runs",
            {
                "forecast_id": fc_prosp_id,
                "protocol_version": "EXPERIMENT_PROTOCOL_V1",
                "generation_mode": "PROSPECTIVE",
                "model_version": "RIDGE_STD_V1",
                "arm": "NO_CHANGE",
                "horizon_publications": 1,
                "generated_at": "2026-11-01 04:10:00",
                "cutoff_time": "2026-11-01 04:10:00",
                "origin_observation_id": orig_obs_id,
                "origin_observed_at": "2026-11-01 04:05:00",
                "origin_source_published_at": "2026-11-01 04:00:00",
                "origin_price_inr_per_g": 13000.0,
                "target_observation_id": None,
                "target_observed_at": None,
                "snapshot_id": snap_id,
            },
        )
        tgt_obs_id = _insert_min_row(
            conn,
            "bullion_rate_observations",
            {
                "city_code": "CHENNAI",
                "product_id": "MJDTA_GOLD_24K",
                "source_product_id": "MJDTA_GOLD",
                "price": 13000.0,
                "normalized_price_per_gram": 13000.0,
                "unit": "1g",
                "rate_type": "MJDTA_BENCHMARK",
                "validation_status": "VALID",
                "observation_kind": "ORIGINAL",
                "revision_number": 1,
                "source_published_at": "2026-11-02 04:00:00",
                "observed_at": "2026-11-02 04:05:00",
            },
        )
        eid = _insert_min_row(
            conn,
            "forecast_evaluations",
            {
                "forecast_id": fc_prosp_id,
                "protocol_version": "EXPERIMENT_PROTOCOL_V1",
                "model_version": "RIDGE_STD_V1",
                "generation_mode": "PROSPECTIVE",
                "arm": "NO_CHANGE",
                "horizon_publications": 1,
                "origin_observed_at": "2026-11-01 04:05:00",
                "target_observation_id": tgt_obs_id,
                "matured_observed_at": "2026-11-02 04:05:00",
                "actual_price_inr_per_g": 13000.0,
                "actual_log_return": 0.0,
                "actual_direction": "FLAT",
                "evaluated_at": "2026-11-02 04:10:00",
            },
        )
        fc_bt_id = f"fc_bt_{uuid.uuid4().hex[:8]}"
        _insert_min_row(
            conn,
            "forecast_runs",
            {
                "forecast_id": fc_bt_id,
                "generation_mode": "BACKTEST",
                "snapshot_id": snap_id,
            },
        )
        bid = _insert_min_row(conn, "forecast_evaluations", {"forecast_id": fc_bt_id, "generation_mode": "BACKTEST"})
        conn.execute(text("DELETE FROM forecast_evaluations WHERE id=:i"), {"i": bid})
    with pytest.raises(TRIGGER_ERRORS):
        with migrated.begin() as conn:
            conn.execute(text("UPDATE forecast_evaluations SET generation_mode='BACKTEST' WHERE id=:i"), {"i": eid})
    with pytest.raises(TRIGGER_ERRORS):
        with migrated.begin() as conn:
            conn.execute(text("UPDATE forecast_evaluations SET id=id WHERE id=:i"), {"i": eid})
    with pytest.raises(TRIGGER_ERRORS):
        with migrated.begin() as conn:
            conn.execute(text("DELETE FROM forecast_evaluations WHERE id=:i"), {"i": eid})


def test_a3_4_news_labels_are_append_only(migrated):
    with migrated.begin() as conn:
        cid = f"clu_{uuid.uuid4().hex[:8]}"
        _insert_min_row(
            conn,
            "news_clusters",
            {"story_cluster_id": cid, "first_seen_at": "2026-11-10 09:00:00", "latest_published_at": "2026-11-10 09:00:00"},
        )
        aid = _insert_min_row(
            conn,
            "news_articles",
            {
                "story_cluster_id": cid,
                "published_at": "2026-11-10 08:30:00",
                "first_seen_at": "2026-11-10 09:00:00",
            },
        )
        lid = _insert_min_row(
            conn,
            "news_labels",
            {
                "article_id": aid,
                "story_cluster_id": cid,
                "collection_run_id": None,
                "label_created_at": "2026-11-10 10:00:00",
                "available_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "db_recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "gold_impact": "BULLISH",
            },
        )
    with pytest.raises(TRIGGER_ERRORS):
        with migrated.begin() as conn:
            conn.execute(text("UPDATE news_labels SET gold_impact='BEARISH' WHERE id=:i"), {"i": lid})
    with pytest.raises(TRIGGER_ERRORS):
        with migrated.begin() as conn:
            conn.execute(text("DELETE FROM news_labels WHERE id=:i"), {"i": lid})
    with migrated.begin() as conn:
        assert conn.execute(text("SELECT gold_impact FROM news_labels WHERE id=:i"), {"i": lid}).scalar() == "BULLISH"


# ---------------------------------------------------------------------------
# A3-7: Ollama persistence is idempotent and rolls back on error
# ---------------------------------------------------------------------------
class _FakeSession:
    def __init__(self, inner, fail_commit=False):
        self.inner, self.fail_commit, self.rolled_back = inner, fail_commit, False

    def execute(self, *a, **k):
        return self.inner.execute(*a, **k)

    def add(self, obj):
        self.inner.add(obj)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")
        self.inner.commit()

    def rollback(self):
        self.rolled_back = True
        self.inner.rollback()


def _fixed_result():
    from app.services.sentiment.schemas import (
        GeneralTone, GoldImpactDirection, GoldMacroDriver, GoldSentimentResult, MacroSurprise,
    )

    return GoldSentimentResult(
        general_tone=GeneralTone.NEUTRAL, gold_impact=GoldImpactDirection.BULLISH,
        driver=GoldMacroDriver.FED_POLICY, surprise=MacroSurprise.UNKNOWN, is_price_report=False,
        confidence="MEDIUM", evidence_rationale="test", sentiment_version="OLLAMA_TEST_V1",
        model_name="qwen-test", model_digest="abc", prompt_version="p1",
    )


def test_a3_7_ollama_classify_and_persist_idempotent_and_rolls_back(migrated, monkeypatch):
    from app.models.research import NewsLabelRecord
    from app.services.ollama.classifier import OllamaGoldClassifier

    clf = OllamaGoldClassifier.__new__(OllamaGoldClassifier)
    monkeypatch.setattr(clf, "classify_headline", lambda **kw: _fixed_result(), raising=False)
    Session = sessionmaker(bind=migrated)
    with Session() as s:
        for _ in range(3):
            clf.classify_and_persist(s, story_cluster_id="clu_x", title="Fed cuts rates")
        n = s.execute(select(NewsLabelRecord).where(NewsLabelRecord.story_cluster_id == "clu_x")).scalars().all()
        assert len(n) == 1

        fs = _FakeSession(s, fail_commit=True)
        with pytest.raises(RuntimeError):
            clf.classify_and_persist(fs, story_cluster_id="clu_y", title="Fed cuts rates")
        assert fs.rolled_back is True


def test_a3_5_parser_marks_clock_only_fixture_precision():
    from app.services.kjpl.city_parser import parse_kjpl_all_city_rates

    html = (Path(__file__).parent / "fixtures" / "kjpl" / "kjpl_live_sample.html").read_text(encoding="utf-8")
    payload = parse_kjpl_all_city_rates(html)
    assert payload.source_updated_time == "Time : 09:35 am"
    assert payload.source_timestamp_precision == "CLOCK_ONLY"


def test_db_path_cpi_and_ppi_stories_get_distinct_clusters_but_syndicated_copies_merge(migrated):
    from app.models.research import NewsArticleRecord
    from app.services.sentiment.label_store import persist_news_collection_to_db
    from app.services.sentiment.schemas import NewsArticle

    t0 = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)

    def run(db, title, url, at, rid):
        art = NewsArticle(title=title, url=url, source="S", published_at=at, language="en", ingested_at=at, first_seen_at=at)
        d = assign_story_clusters([{"published_at": art.published_at, "title": art.title}])[0]
        art.story_cluster_id, art.cluster_key, art.cluster_version = d["story_cluster_id"], d["cluster_key"], d["cluster_version"]
        persist_news_collection_to_db(db, run_id=rid, started_at=at, completed_at=at, status="SUCCESS", articles=[art],
                                      health={"queries_attempted": 11, "queries_succeeded": 11}, stats={}, label_created_at=at)

    def cid(db, url):
        return db.execute(select(NewsArticleRecord.story_cluster_id).where(NewsArticleRecord.canonical_url.like(f"%{url}"))).scalar()

    Session = sessionmaker(bind=migrated)
    with Session() as db:
        run(db, "Gold slips as dollar firms ahead of US CPI data release", "https://ex.com/m1", t0, "m1")
        run(db, "Gold slips as dollar firms ahead of US PPI data release", "https://ex.com/m2", t0 + timedelta(hours=1), "m2")
        run(db, "Gold slips as dollar firms ahead of US CPI data release - Mint", "https://ex2.com/m3", t0 + timedelta(hours=2), "m3")
        assert cid(db, "/m1") != cid(db, "/m2")
        assert cid(db, "/m1") == cid(db, "/m3")
