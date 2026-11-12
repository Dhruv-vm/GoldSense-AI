"""Second-audit adversarial test: F-01 (MJDTA DB continuity) and F-02 (prospective ledger).
Runs against a LOCAL temporary PostgreSQL only. Synthetic fixtures only."""
from __future__ import annotations

import datetime as _dt
import sys
from datetime import timedelta, timezone

from sqlalchemy import select, func, text

from _db_guard import ensure_disposable_audit_db
ensure_disposable_audit_db()

import app.db.session as dbs
from app.db.base import Base
import app.models  # noqa
from app.models.bullion import BullionRateObservation
from app.models.research import ForecastRun, ForecastEvaluation, ResearchFeatureSnapshot
import app.services.kjpl.persistence as P
from app.services.kjpl import city_schemas as cs
from app.services.kjpl.city_parser import _build_validated_item
from app.services.prediction.mjdta_series import load_mjdta_observations_from_db
import app.services.prediction.forecast_engine as fe

T0 = _dt.datetime(2026, 9, 1, 4, 30, tzinfo=timezone.utc)


class _Clock:
    now_value = T0


class FrozenDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        v = _Clock.now_value
        return v if tz is None else v.astimezone(tz)


P.datetime = FrozenDT  # freeze persistence clock only


def mjdta_item(price: float, city: str = "CHENNAI", spid: str = "MJDTA_GOLD"):
    return _build_validated_item(
        city_code=city, city_display_name=city.title(), product_id="MJDTA_GOLD_24K",
        product_name="MJDTA Gold 24K", metal="GOLD", purity=0.999, weight=1.0, unit="1g",
        rate_type="MJDTA_BENCHMARK", price=price, currency="INR", source_product_id=spid,
        raw_source_name="MJDTA GOLD (Without GST)",
    )


def publish(day: int, price: float, city: str = "CHENNAI", spid: str = "MJDTA_GOLD"):
    t = T0 + timedelta(days=day)
    _Clock.now_value = t
    payload = cs.ParsedKJPLPayload(
        observed_at=t, pipeline="MJDTA", source_updated_time="10:00 am", source_updated_at=t - timedelta(minutes=30),
        market_status="OPEN", rate_display_enabled=True, city_rates=[mjdta_item(price, city, spid)],
        quarantined_rates=[], raw_products_count=1, extraction_errors=[],
    )
    return P.persist_parsed_payload(payload, source_key="KJPL_MJDTA", mirror_csv=False)


def main():
    db = dbs.SessionLocal()
    print("dialect:", dbs.engine.dialect.name)
    P.seed_bullion_metadata(db)

    # --- F-01(a): 20 daily publications, 6 of which repeat the previous day's price
    prices = [13000, 13050, 13050, 13100, 13020, 13020, 13080, 13150, 13150, 13110,
              13060, 13060, 13120, 13180, 13200, 13200, 13140, 13090, 13130, 13170]
    for d, p in enumerate(prices):
        publish(d, float(p))
    n_db = db.execute(select(func.count()).select_from(BullionRateObservation).where(
        BullionRateObservation.product_id == "MJDTA_GOLD_24K", BullionRateObservation.validation_status == "VALID")).scalar()
    obs, summ = load_mjdta_observations_from_db(db)
    elig = [o for o in obs if o.is_eligible_publication]
    print(f"F-01a publications={len(prices)} VALID_obs_rows={n_db} eligible_series_len={len(elig)}")

    # --- F-01(b): ALL_INDIA contamination with a plausible value at a different time
    _Clock.now_value = T0 + timedelta(days=19, hours=6)
    payload = cs.ParsedKJPLPayload(observed_at=_Clock.now_value, pipeline="SNAPSHOT", source_updated_time="4:00 pm",
        source_updated_at=_Clock.now_value, market_status="OPEN", rate_display_enabled=True,
        city_rates=[mjdta_item(13431.2, "ALL_INDIA", "GOLD")], quarantined_rates=[], raw_products_count=1, extraction_errors=[])
    P.persist_parsed_payload(payload, source_key="KJPL_LIVE", mirror_csv=False)
    obs2, _ = load_mjdta_observations_from_db(db)
    elig2 = [o for o in obs2 if o.is_eligible_publication]
    print(f"F-01b after ALL_INDIA row (source_product_id='GOLD'): series_len={len(elig2)} last_price={elig2[-1].gold_mjdta_inr_per_g}")

    # --- F-02: prospective frontier forecast, idempotency, hindsight guard, model change
    gen1 = T0 + timedelta(days=19, hours=8)
    r1 = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1)
    print("F-02 run1:", r1.get("status"), "persisted:", r1.get("persisted"), "origin:", r1.get("origin_observed_at"))
    r2 = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1 + timedelta(hours=1))
    print("F-02 run2 (same origin, 1h later):", r2.get("persisted"))
    fr = db.execute(select(func.count()).select_from(ForecastRun).where(ForecastRun.generation_mode == "PROSPECTIVE")).scalar()
    sn = db.execute(select(func.count()).select_from(ResearchFeatureSnapshot)).scalar()
    print(f"   prospective ForecastRun rows={fr} snapshots={sn}")
    print("   statuses:", sorted({(r.arm, r.horizon_publications, r.status) for r in db.execute(select(ForecastRun)).scalars()}))

    # model version change under same protocol
    old_mv = fe.MODEL_VERSION
    fe.MODEL_VERSION = "RIDGE_STD_V2_AUDIT"
    r3 = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1 + timedelta(hours=2))
    mv = sorted({r.model_version for r in db.execute(select(ForecastRun)).scalars()})
    print("F-02 model-version change: persisted:", r3.get("persisted"), "model_versions in ledger:", mv)
    fe.MODEL_VERSION = old_mv

    # backtest into prospective writer
    bt = fe.run_backtest_study(obs2, [], None)
    try:
        snap = bt["snapshots"][-1]
        fcs = [fe.ShadowForecastRecord(**f) for f in bt["forecasts"] if f["origin_observed_at"] == snap["origin_observed_at"]]
        fe.persist_prospective_forecast_run(db, snapshot=snap, forecasts=fcs)
        print("F-02 backtest->prospective writer: ACCEPTED (defect)")
    except Exception as e:
        db.rollback(); print("F-02 backtest->prospective writer: rejected:", type(e).__name__)

    # hindsight: forge a PROSPECTIVE forecast for an OLD origin (targets already exist)
    old = elig2[10]
    forged = fe.ShadowForecastRecord(forecast_id="fc_forged", protocol_version=fe.PROTOCOL_VERSION, generation_mode="PROSPECTIVE",
        model_version=fe.MODEL_VERSION, arm="NO_CHANGE", horizon_publications=1, generated_at=(gen1).isoformat(),
        cutoff_time=gen1.isoformat(), origin_observation_id=old.observation_id, origin_observed_at=old.observed_at_utc.isoformat(),
        origin_price_inr_per_g=old.gold_mjdta_inr_per_g, target_observation_id=None, target_observed_at=None,
        snapshot_id="snap_forged", feature_hash="x", predicted_log_return=0.0, predicted_price_inr_per_g=old.gold_mjdta_inr_per_g,
        predicted_direction="FLAT", up_probability=0.5, status="PROSPECTIVE_ACTIVE", coverage_ok=False)
    snapd = dict(r1.get("snapshot") or {}) or {}
    snapd = {"snapshot_id": "snap_forged", "generation_mode": "PROSPECTIVE", "cutoff_time": gen1.isoformat(),
             "label_cutoff_time": gen1.isoformat(), "target_product": "MJDTA_GOLD_24K", "origin_observation_id": old.observation_id,
             "origin_observed_at": old.observed_at_utc.isoformat(), "origin_gold_price_inr_per_g": old.gold_mjdta_inr_per_g,
             "feature_version": "x", "cluster_version": "x", "sentiment_version": "x", "feature_hash": "x", "n_clusters_relevant": 0,
             "net_impact": None, "unknown_share": None, "coverage_ok": False, "features_json": {}}
    try:
        fe.persist_prospective_forecast_run(db, snapshot=snapd, forecasts=[forged])
        print("F-02 hindsight forged old-origin forecast: ACCEPTED (defect)")
    except Exception as e:
        db.rollback(); print("F-02 hindsight forged old-origin forecast: rejected:", str(e)[:90])

    # DB-level hindsight guard? direct ORM insert bypassing the writer
    try:
        db.add(ForecastRun(forecast_id="fc_direct", protocol_version="P", generation_mode="PROSPECTIVE", model_version="M", arm="NO_CHANGE",
            horizon_publications=1, generated_at=gen1 + timedelta(days=30), cutoff_time=old.observed_at_utc, origin_observation_id=old.observation_id,
            origin_observed_at=old.observed_at_utc, origin_price_inr_per_g=13000, target_observation_id=None, target_observed_at=None,
            snapshot_id=r1.get("snapshot_id") or db.execute(select(ResearchFeatureSnapshot.snapshot_id)).scalars().first(), feature_hash="x",
            predicted_log_return=0.0, predicted_price_inr_per_g=13000, predicted_direction="FLAT", up_probability=0.5, status="X", is_immutable=True))
        db.commit(); print("F-02 direct ORM insert of hindsight PROSPECTIVE row: ACCEPTED by DB (no DB-level guard)")
    except Exception as e:
        db.rollback(); print("F-02 direct ORM insert: rejected by DB:", type(e).__name__)

    # immutability: can an existing prospective forecast be UPDATED?
    row = db.execute(select(ForecastRun).where(ForecastRun.generation_mode == "PROSPECTIVE", ForecastRun.arm == "PRICE_ONLY")).scalars().first()
    try:
        row.predicted_log_return = 0.0999; db.commit()
        print("F-02 UPDATE of persisted prospective prediction: ACCEPTED (no DB immutability)")
    except Exception as e:
        db.rollback(); print("F-02 UPDATE rejected:", type(e).__name__)

    # --- maturation: publish 3 more days, evaluate
    for k, p in enumerate([13210, 13250, 13190]):
        publish(20 + k, float(p))
    ev = fe.evaluate_matured_prospective_forecasts(db)
    nev = db.execute(select(func.count()).select_from(ForecastEvaluation).where(ForecastEvaluation.generation_mode == "PROSPECTIVE")).scalar()
    print("F-02 maturation:", ev, "eval rows:", nev)
    r4 = fe.generate_prospective_forecast_for_frontier(db, generated_at=T0 + timedelta(days=22, hours=8))
    print("F-01c new MJDTA record becomes next frontier origin:", r4.get("status"), r4.get("origin_observed_at"))
    db.close()


if __name__ == "__main__":
    main()
