"""Challenge probes against the remediated code (synthetic data, throwaway SQLite with Alembic triggers)."""
import sys, subprocess, tempfile, os, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, ".")
from sqlalchemy import select, create_engine, func
from sqlalchemy.orm import sessionmaker
IST = ZoneInfo("Asia/Kolkata"); UTC = timezone.utc

from app.services.kjpl.parser import resolve_clock_only_kjpl_time
print("== clock-only resolution")
now = datetime(2026, 11, 11, 9, 30, tzinfo=IST)
for txt in ("09:34 am", "09:36 am", "12:00 am", "12:30 pm", "11:59 pm"):
    resolved = resolve_clock_only_kjpl_time(txt, now)
    print(f"   now 09:30, page '{txt}' ->", resolved.isoformat() if resolved is not None else "QUARANTINED/UNAVAILABLE (None)")

# Migrated SQLite (triggers on)
from tests.test_research_forecast_and_leakage import _setup_migrated_sqlite_session
import app.db.session as dbs
tmp = Path(tempfile.mkdtemp())
Session, eng, oe, os_ = _setup_migrated_sqlite_session(tmp, "c.db", None)
import app.services.kjpl.persistence as P
from app.services.kjpl import city_schemas as cs
from app.services.kjpl.city_parser import _build_validated_item
from app.models.bullion import BullionRateObservation
from app.services.prediction.mjdta_series import load_mjdta_observations_from_db
import app.services.prediction.forecast_engine as fe
from app.models.research import ForecastRun, ResearchFeatureSnapshot, NewsLabelRecord

class Clock: v = datetime(2026, 9, 1, tzinfo=timezone.utc)
class FDT(datetime):
    @classmethod
    def now(cls, tz=None): return Clock.v if tz is None else Clock.v.astimezone(tz)
P.datetime = FDT

def item(p): return _build_validated_item(city_code="CHENNAI", city_display_name="Chennai", product_id="MJDTA_GOLD_24K", product_name="M", metal="GOLD", purity=0.999, weight=1.0, unit="1g", rate_type="MJDTA_BENCHMARK", price=float(p), currency="INR", source_product_id="MJDTA_GOLD", raw_source_name="MJDTA GOLD")
def poll(db, obs_ist, pub_ist, price, precision, text=None):
    Clock.v = obs_ist.astimezone(UTC)
    src_txt = text or (pub_ist.strftime("%d-%m-%Y %I:%M:%S %p") if pub_ist is not None else None)
    pl = cs.ParsedKJPLPayload(observed_at=Clock.v, pipeline="MJDTA", source_updated_time=src_txt,
        source_updated_at=pub_ist, source_timestamp_precision=precision, city_rates=[item(price)])
    return P.persist_parsed_payload(pl, session=db, source_key="KJPL_MJDTA", mirror_csv=False)
def nvalid(db): return db.execute(select(func.count()).select_from(BullionRateObservation).where(BullionRateObservation.validation_status=="VALID", BullionRateObservation.product_id=="MJDTA_GOLD_24K")).scalar()

with Session() as db:
    P.seed_bullion_metadata(db)
    d0 = datetime(2026, 9, 1, tzinfo=IST)
    print("== future quarantine (FULL timestamps)")
    for mins in (9, 11):
        r = poll(db, d0.replace(hour=9, minute=0), d0.replace(hour=9, minute=mins), 13000 + mins, "FULL")
        print(f"   FULL pub {mins} min after observation -> quarantined={r['records_quarantined']}")
    print("== clock skew: KJPL clock 7 min AHEAD of runner, fresh publication, clock-only")
    obs = d0.replace(day=2, hour=9, minute=30)
    pub = resolve_clock_only_kjpl_time("09:37 am", obs)
    r = poll(db, obs, pub, 13100, "CLOCK_ONLY", "Time : 09:37 am")
    pub_label = pub.isoformat() if pub is not None else "QUARANTINED/UNAVAILABLE (None)"
    print(f"   page '09:37 am' polled at 09:30 -> stored as {pub_label}, result={r['item_logs'][-1]['persistence_result']}")
    print("== genuine same-minute, same-price publication on consecutive days (clock-only)")
    n0 = nvalid(db)
    poll(db, d0.replace(day=5, hour=10), d0.replace(day=5, hour=9, minute=30), 13200, "FULL")
    n1 = nvalid(db)
    r = poll(db, d0.replace(day=6, hour=10), d0.replace(day=6, hour=9, minute=30), 13200, "CLOCK_ONLY", "Time : 09:30 am")
    print(f"   day5 FULL +{n1-n0}; day6 genuine CLOCK_ONLY same price/minute -> +{nvalid(db)-n1} ({r['item_logs'][-1]['persistence_result']})")

    print("== correction of the frontier origin AFTER prospective forecasts were logged")
    base = datetime(2026, 9, 10, tzinfo=IST)
    for k in range(25):
        poll(db, base + timedelta(days=k, hours=10), base + timedelta(days=k, hours=9, minutes=30), 13300 + 7 * (k % 5), "FULL")
    last_pub = base + timedelta(days=24, hours=9, minutes=30)
    gen1 = (base + timedelta(days=24, hours=11)).astimezone(UTC)
    r1 = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen1); db.commit()
    poll(db, base + timedelta(days=24, hours=12), last_pub, 13399, "FULL")   # same publication, corrected price
    gen2 = (base + timedelta(days=24, hours=12, minutes=30)).astimezone(UTC)
    try:
        r2 = fe.generate_prospective_forecast_for_frontier(db, generated_at=gen2); db.commit()
    except Exception as e:
        db.rollback(); r2 = {"status": "ERROR " + type(e).__name__, "persisted": str(e)[:100]}
    snaps = db.execute(select(func.count()).select_from(ResearchFeatureSnapshot).where(ResearchFeatureSnapshot.generation_mode=="PROSPECTIVE")).scalar()
    origins = db.execute(select(ForecastRun.origin_observed_at, ForecastRun.origin_price_inr_per_g).where(ForecastRun.generation_mode=="PROSPECTIVE").distinct()).all()
    print("   before correction:", r1.get("status"), r1.get("persisted"))
    print("   after correction :", r2.get("status"), r2.get("persisted"))
    print(f"   PROSPECTIVE snapshots={snaps}; distinct (origin_observed_at, origin_price) = {[(str(o)[:19], float(p)) for o, p in origins]}")

    print("== Ollama idempotency under concurrency (two sessions, same cluster)")
    from app.services.ollama.classifier import OllamaGoldClassifier
    from tests.test_audit3_remediation import _fixed_result
    clf = OllamaGoldClassifier.__new__(OllamaGoldClassifier)
    clf.classify_headline = lambda **kw: _fixed_result()
    barrier = threading.Barrier(2); errs = []
    orig_exec = None
    def worker():
        s = Session()
        try:
            barrier.wait(); clf.classify_and_persist(s, story_cluster_id="clu_conc", title="t")
        except Exception as e: errs.append(type(e).__name__)
        finally: s.close()
    ts = [threading.Thread(target=worker) for _ in range(2)]; [t.start() for t in ts]; [t.join() for t in ts]
    n = db.execute(select(func.count()).select_from(NewsLabelRecord).where(NewsLabelRecord.story_cluster_id=="clu_conc")).scalar()
    print(f"   rows for one (cluster, model, version, hash) after 2 concurrent calls: {n}  errors={errs}")

print("== classifier digest stability across fresh interpreter processes")
code = "import sys; sys.path.insert(0,'.'); from app.services.sentiment.label_store import _classifier_implementation_digest as d; from app.services.sentiment.gold_impact import evaluate_gold_impact as f; print(d(f))"
outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": str(s)}).stdout.strip() for s in (1, 2, 3)}
print("   digests over 3 processes with different hash seeds:", outs)

print("== protocol hash: detects a 1-byte change, ignores CRLF")
from app.services.prediction.protocol import compute_protocol_sha256, PROTOCOL_DOC_PATH, EXPERIMENT_PROTOCOL_V1_SHA256
raw = PROTOCOL_DOC_PATH.read_bytes()
t1 = tmp / "p1.md"; t1.write_bytes(raw.replace(b"\n", b"\r\n")); t2 = tmp / "p2.md"; t2.write_bytes(raw.replace(b"MIN_EVALUATION_SAMPLES = 30", b"MIN_EVALUATION_SAMPLES = 20"))
print("   actual doc matches constant:", compute_protocol_sha256() == EXPERIMENT_PROTOCOL_V1_SHA256)
print("   CRLF copy matches:", compute_protocol_sha256(t1) == EXPERIMENT_PROTOCOL_V1_SHA256, "| edited copy matches:", compute_protocol_sha256(t2) == EXPERIMENT_PROTOCOL_V1_SHA256)
print("   is the hash enforced at runtime (imported by forecast_engine)?", "protocol" in Path("app/services/prediction/forecast_engine.py").read_text().split("def ")[0])
dbs.engine, dbs.SessionLocal = oe, os_
