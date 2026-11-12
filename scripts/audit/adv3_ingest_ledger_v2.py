# UPDATED VARIANT of adv3_ingest_ledger.py (2026-11-11 final verification). Original is unchanged.
# Why: the original assumes the OLD inflated MJDTA series (Sunday carry-over counted as a publication) and
# indexes series[5] / needs >=10 training origins; with the fix the series is shorter, so it stops before the
# F-02 attacks. Changes (marked [V2]): 25 extra synthetic FULL-timestamp publications before F-02; forecast
# generated_at pinned just after the frontier (not wall-clock now) so maturation is real and the evaluation
# UPDATE/DELETE attacks hit actual PROSPECTIVE rows; rows-affected printed for every accepted statement.
# Attack set unchanged.
"""Third-audit adversarial tests (NEW-2, NEW-3, F-02). LOCAL temporary PostgreSQL + synthetic fixtures only."""
from __future__ import annotations

import datetime as _dt
import threading
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, text

import app.db.session as dbs
import app.models  # noqa
from app.models.bullion import BullionRateObservation
from app.models.research import ForecastRun, ForecastEvaluation, ResearchFeatureSnapshot
import app.services.kjpl.persistence as P
from app.services.kjpl import city_schemas as cs
from app.services.kjpl.city_parser import _build_validated_item, _parse_source_clock_time
from app.services.prediction.mjdta_series import load_mjdta_observations_from_db, _normalize_raw_mjdta_sequence
import app.services.prediction.forecast_engine as fe

IST = ZoneInfo("Asia/Kolkata")


class _Clock:
    now_value = _dt.datetime(2026, 9, 1, tzinfo=timezone.utc)


class FrozenDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        v = _Clock.now_value
        return v if tz is None else v.astimezone(tz)


P.datetime = FrozenDT


def item(price, city="CHENNAI", product="MJDTA_GOLD_24K", spid="MJDTA_GOLD", unit="1g", weight=1.0, rate_type="MJDTA_BENCHMARK"):
    return _build_validated_item(city_code=city, city_display_name=city.title(), product_id=product, product_name=product,
        metal="GOLD", purity=0.999, weight=weight, unit=unit, rate_type=rate_type, price=price, currency="INR",
        source_product_id=spid, raw_source_name="MJDTA GOLD")


def poll(observed_ist, clock_text, items):
    """Simulate one KJPL poll at observed_ist: source time derived by the REAL parser helper."""
    _Clock.now_value = observed_ist.astimezone(timezone.utc)
    src = _parse_source_clock_time(clock_text, observed_ist) if clock_text else None
    payload = cs.ParsedKJPLPayload(observed_at=_Clock.now_value, pipeline="MJDTA", source_updated_time=clock_text,
        source_updated_at=src, market_status="OPEN", rate_display_enabled=True, city_rates=items,
        quarantined_rates=[], raw_products_count=len(items), extraction_errors=[])
    P.persist_parsed_payload(payload, source_key="KJPL_MJDTA", mirror_csv=False)
    return src


def series(db):
    obs, summ = load_mjdta_observations_from_db(db)
    return [o for o in obs if o.is_eligible_publication], obs


def main():
    db = dbs.SessionLocal()
    P.seed_bullion_metadata(db)

    print("=== NEW-2(a) replay REAL kjpl_rates.csv rows 19/20/21 Sep (Sat, Sun carry-over, Mon) ===")
    real = [(_dt.datetime(2026, 9, 19, 20, 6, tzinfo=IST), "Time : 09:29 am", 14285.0),
            (_dt.datetime(2026, 9, 20, 15, 30, tzinfo=IST), "Time : 09:29 am", 14285.0),
            (_dt.datetime(2026, 9, 21, 16, 30, tzinfo=IST), "Time : 09:29 am", 14270.0)]
    for o, c, p in real:
        print("   poll", o.isoformat(), "-> source_published_at", poll(o, c, [item(p)]).isoformat())
    el, allobs = series(db)
    csv_rows = [{"observation_id": i, "observed_at_utc": o.astimezone(timezone.utc), "explicit_source_published_at": None,
                 "published_time_raw": c, "gold": p, "silver": None, "source": "KJPL", "is_changed": True} for i, (o, c, p) in enumerate(real)]
    csv_obs, _ = _normalize_raw_mjdta_sequence(csv_rows, require_explicit_timestamp=False)
    print(f"   DB-path eligible={len(el)} statuses={[o.timestamp_status for o in allobs]}")
    print(f"   CSV-path eligible={sum(o.is_eligible_publication for o in csv_obs)} statuses={[o.timestamp_status for o in csv_obs]}")

    print("=== NEW-2(b) early-morning poll (06:08 IST, cron 00:38 UTC) before the day's 09:30 publication ===")
    d = _dt.datetime(2026, 9, 22, tzinfo=IST)
    s1 = poll(d.replace(hour=6, minute=8), "Time : 09:29 am", [item(14270.0)])   # still yesterday's rate on page
    s2 = poll(d.replace(hour=14, minute=8), "Time : 09:31 am", [item(14300.0)])  # today's real publication
    el2, _ = series(db)
    print(f"   06:08 poll stamped source_published_at={s1.isoformat()} (in the future of the poll by {(s1 - d.replace(hour=6, minute=8))})")
    print(f"   series grew {len(el)} -> {len(el2)} for ONE real publication; last 3 prices {[o.gold_mjdta_inr_per_g for o in el2[-3:]]}")

    print("=== NEW-2(c) repeated polling of the same publication; correction; missing timestamp ===")
    n0 = len(series(db)[0])
    for h in (8, 9):
        poll(d.replace(hour=h, minute=38) + timedelta(days=1), "Time : 09:30 am", [item(14310.0)])
    poll(d.replace(hour=10, minute=8) + timedelta(days=1), "Time : 09:30 am", [item(14310.0)])
    n1 = len(series(db)[0])
    poll(d.replace(hour=11, minute=8) + timedelta(days=1), "Time : 09:30 am", [item(14320.0)])  # same source time, corrected price
    n2 = len(series(db)[0])
    poll(d.replace(hour=12, minute=8) + timedelta(days=1), None, [item(14330.0)])
    n3 = len(series(db)[0])
    q = db.execute(select(func.count()).select_from(BullionRateObservation).where(BullionRateObservation.validation_status == "QUARANTINED",
        BullionRateObservation.quarantine_reason.like("Missing genuine source_published_at%"))).scalar()
    print(f"   3 polls of one publication: +{n1 - n0} | same-time corrected price: +{n2 - n1} | missing timestamp: +{n3 - n2}, quarantined rows={q}")

    print("=== NEW-3 contamination attempts (each VALID via the real persistence path) ===")
    base = len(series(db)[0])
    t = d + timedelta(days=2)
    attempts = [("ALL_INDIA city", item(14999.0, city="ALL_INDIA")), ("MUMBAI city", item(14998.0, city="MUMBAI")),
                ("wrong source_product_id", item(14997.0, spid="GOLD")), ("GST product", item(14996.0, product="MJDTA_GOLD_24K_GST")),
                ("unit 10g quote", item(149950.0, unit="10g", weight=10.0)),
                ("rate_type RETAIL", item(14994.0, rate_type="RETAIL"))]
    for k, (name, it) in enumerate(attempts):
        poll(t.replace(hour=10 + k), "Time : 10:0%d am" % k, [it])
        el_now = series(db)[0]
        print(f"   {name:24} status={it.validation_status:11} series {base}->{len(el_now)} last={el_now[-1].gold_mjdta_inr_per_g}")
        base = len(el_now)

    # [V2] extra synthetic history with FULL timestamps
    hist0 = d + timedelta(days=3)
    for k in range(25):
        o = hist0 + timedelta(days=k, hours=10)
        _Clock.now_value = o.astimezone(timezone.utc)
        pub = hist0 + timedelta(days=k, hours=9, minutes=30)
        P.persist_parsed_payload(cs.ParsedKJPLPayload(observed_at=_Clock.now_value, pipeline="MJDTA",
            source_updated_time=pub.strftime("%d-%m-%Y %I:%M:%S %p"), source_updated_at=pub, market_status="OPEN",
            rate_display_enabled=True, city_rates=[item(14330.0 + 5 * (k % 7))], quarantined_rates=[], raw_products_count=1,
            extraction_errors=[]), source_key="KJPL_MJDTA", mirror_csv=False)
    d = hist0 + timedelta(days=25)
    print("=== F-02 ledger attacks ===")
    gen = (d - timedelta(days=1) + timedelta(hours=11)).astimezone(timezone.utc)  # [V2] just after the frontier publication
    r = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen)
    print("   frontier:", r.get("status"), r.get("persisted"))
    for k in range(2):
        r2 = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen + timedelta(minutes=10 * (k + 1)))
    print("   snapshots after 3 identical runs:", db.execute(select(func.count()).select_from(ResearchFeatureSnapshot).where(ResearchFeatureSnapshot.generation_mode == "PROSPECTIVE")).scalar())

    def attempt(label, sql):
        try:
            rc = db.execute(text(sql)).rowcount; db.commit(); print(f"   {label}: ACCEPTED (rows affected={rc})")
        except Exception as e:
            db.rollback(); print(f"   {label}: rejected ({str(e).splitlines()[0][:95]})")

    old = series(db)[0][5]
    attempt("INSERT hindsight PROSPECTIVE (raw SQL)", f"""INSERT INTO forecast_runs (forecast_id,protocol_version,generation_mode,model_version,arm,horizon_publications,generated_at,cutoff_time,origin_observation_id,origin_observed_at,origin_price_inr_per_g,snapshot_id,feature_hash,predicted_log_return,predicted_price_inr_per_g,predicted_direction,up_probability,status,is_immutable,created_at)
      SELECT 'fc_hind','P','PROSPECTIVE','M','NO_CHANGE',1,now(),now(),{old.observation_id},'{old.observed_at_utc.isoformat()}',13000,snapshot_id,'x',0,13000,'FLAT',0.5,'X',true,now() FROM research_feature_snapshots LIMIT 1""")
    attempt("INSERT BACKTEST row for same old origin", f"""INSERT INTO forecast_runs (forecast_id,protocol_version,generation_mode,model_version,arm,horizon_publications,generated_at,cutoff_time,origin_observation_id,origin_observed_at,origin_price_inr_per_g,snapshot_id,feature_hash,predicted_log_return,predicted_price_inr_per_g,predicted_direction,up_probability,status,is_immutable,created_at)
      SELECT 'fc_bt','P','BACKTEST','M','NO_CHANGE',1,now(),now(),{old.observation_id},'{old.observed_at_utc.isoformat()}',13000,snapshot_id,'x',0,13000,'FLAT',0.5,'X',false,now() FROM research_feature_snapshots LIMIT 1""")
    attempt("UPDATE that BACKTEST row -> generation_mode='PROSPECTIVE'", "UPDATE forecast_runs SET generation_mode='PROSPECTIVE' WHERE forecast_id='fc_bt'")
    print("   PROSPECTIVE rows whose origin already had matured targets at insert:",
          db.execute(text("select count(*) from forecast_runs where generation_mode='PROSPECTIVE' and forecast_id='fc_bt'")).scalar())
    attempt("UPDATE PROSPECTIVE prediction", "UPDATE forecast_runs SET predicted_log_return=0.5 WHERE generation_mode='PROSPECTIVE' AND forecast_id<>'fc_bt'")
    attempt("DELETE PROSPECTIVE row", "DELETE FROM forecast_runs WHERE generation_mode='PROSPECTIVE' AND arm='NO_CHANGE' AND forecast_id<>'fc_bt'")

    # mature then attack evaluations
    t3 = d + timedelta(days=5)
    for k in range(3):
        poll(t3 + timedelta(days=k, hours=10), "Time : 09:3%d am" % k, [item(14400.0 + 10 * k)])
    print("   maturation:", fe.evaluate_matured_prospective_forecasts(db))
    print("   [V2] PROSPECTIVE evaluation rows before attacks:", db.execute(text("select count(*) from forecast_evaluations where generation_mode='PROSPECTIVE'")).scalar())
    attempt("UPDATE PROSPECTIVE evaluation outcome", "UPDATE forecast_evaluations SET actual_log_return=0.123 WHERE generation_mode='PROSPECTIVE'")
    attempt("DELETE PROSPECTIVE evaluations", "DELETE FROM forecast_evaluations WHERE generation_mode='PROSPECTIVE'")
    attempt("TRUNCATE forecast_runs CASCADE", "TRUNCATE forecast_runs CASCADE")
    print("   forecast_runs remaining:", db.execute(text("select count(*) from forecast_runs")).scalar())
    db.close()

    print("=== F-02 concurrency: two writers on a new frontier origin ===")
    s = dbs.SessionLocal(); P.seed_bullion_metadata(s); s.close()
    poll(t3 + timedelta(days=4, hours=10), "Time : 09:40 am", [item(14500.0)])
    results = []

    def worker(k):
        sess = dbs.SessionLocal()
        try:
            results.append(("ok", fe.generate_prospective_forecast_for_frontier(sess, generated_at=(t3 + timedelta(days=4, hours=11)).astimezone(timezone.utc) + timedelta(seconds=k)).get("persisted")))
        except Exception as e:
            sess.rollback(); results.append(("error", type(e).__name__ + ": " + str(e).splitlines()[0][:80]))
        finally:
            sess.close()
    th = [threading.Thread(target=worker, args=(k,)) for k in range(2)]
    [x.start() for x in th]; [x.join() for x in th]
    print("  ", results)


if __name__ == "__main__":
    main()
