from app.jobs.feature_job import run_feature_snapshot
from app.jobs.kjpl_job import run_kjpl_collection
from app.jobs.market_job import run_market_collection


def run_goldsense_pipeline():
    print("[PIPELINE] Starting GoldSense data collection...")

    run_kjpl_collection()
    run_market_collection()
    run_feature_snapshot()

    print("[PIPELINE] GoldSense data collection complete.")